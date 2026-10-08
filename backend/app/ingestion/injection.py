"""Indirect prompt-injection detector (docs/AI_CONTEXT_ENGINEERING.md §A1).

Deterministic, multilingual (FR/EN) rules scoring every chunk at ingestion:

* instructions addressed to a model (« ignore les instructions précédentes », "you are now…");
* fake system / role markers (``system:``, ``<|im_start|>``, ``[INST]``…);
* requests to reveal or send secrets, exfiltration links (markdown image with a query string,
  URL templates such as ``https://x.example/?q={data}``);
* suspicious tags / encodings (``<script>``, ``javascript:``, ``data:…;base64``, long base64 blobs,
  Unicode tag characters, bidi overrides);
* hidden text: zero-width characters, CSS-hidden HTML (``display:none``, ``font-size:0``…).

Each rule has a weight; the chunk score is ``1 - Π(1 - w)`` over the matched rules (in ``[0, 1]``).
A chunk whose score reaches ``ORBIT_INJECTION_THRESHOLD`` is quarantined (never served, reason code
``EXCLUDED_QUARANTINE``) until an owner releases it. An optional local classifier can be plugged with
``ORBIT_INJECTION_CLASSIFIER=local`` (never an external call); without it the rules are the sole signal.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_I = re.IGNORECASE | re.UNICODE


@dataclass(frozen=True, slots=True)
class _Rule:
    code: str
    label: str
    weight: float
    patterns: tuple[re.Pattern[str], ...]


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, _I) for p in patterns)


RULES: tuple[_Rule, ...] = (
    _Rule(
        "IGNORE_INSTRUCTIONS",
        "Consigne de contournement (« ignore les instructions… »)",
        0.7,
        _rx(
            r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|"
            r"your|the system)\b[^.\n]{0,30}\b(instructions?|prompts?|rules|directives|guidelines)\b",
            r"\b(ignorez?|ignorer|oubliez?|oublier|ne (?:tiens|tenez) (?:pas|plus) compte d?e?s?|"
            r"fais abstraction des|faites abstraction des)\s+(?:de\s+)?(?:toutes?\s+)?(?:les|tes|vos)\s+"
            r"(?:\w+\s+)?(instructions|consignes|directives|règles)\s+(précédentes|antérieures|ci-dessus|"
            r"plus haut|initiales|système|du système)",
            r"\b(ignorez?|ignorer|oubliez?|oublier)\s+(toutes\s+(?:les|tes|vos)|tes|vos)\s+"
            r"(instructions|consignes|directives|règles)\b",
        ),
    ),
    _Rule(
        "ROLE_MARKER",
        "Faux marqueur de rôle système",
        0.55,
        _rx(
            r"(?m)^\s*#*\s*(system|assistant|developer|système)\s*(prompt)?\s*:",
            r"<\|\s*(im_start|im_end|system|endoftext|assistant)\s*\|>",
            r"\[/?(INST|SYS)\]",
            r"<</?SYS>>",
            r"</?(system|instructions?|untrusted_content|orbit_context)>",
        ),
    ),
    _Rule(
        "ADDRESSED_TO_MODEL",
        "Instruction adressée à un modèle d'IA",
        0.45,
        _rx(
            r"\b(you are now|act as an?|pretend (to be|you are)|from now on,? you|"
            r"as an ai (language )?model,? you|"
            r"(dear|hey) (ai|assistant|llm|chatbot|agent|model)\b|(note|message|instructions?) (to|for) "
            r"(the )?(ai|assistant|llm|agent|model)\b|new instructions:)",
            r"\b(tu es désormais|vous êtes désormais|à partir de maintenant,? (tu|vous)|"
            r"agis comme|agissez comme|"
            r"fais semblant d'être|(cher|chère) (ia|assistant|agent|modèle)\b|(note|message|consignes?) "
            r"(pour|à) l'(ia|assistant|agent|modèle)\b|(à|pour) l'attention de l'(ia|assistant|agent)\b|"
            r"nouvelles consignes\s*:)",
        ),
    ),
    _Rule(
        "SECRET_REQUEST",
        "Demande de divulgation de secrets ou du prompt",
        0.5,
        _rx(
            r"\b(reveal|print|output|repeat|send|leak|disclose|exfiltrate|share)\b[^.\n]{0,40}\b("
            r"system prompt|"
            r"your instructions|api[ _-]?keys?|passwords?|secrets?|credentials|access tokens?)\b",
            r"\b(révèle|révélez|affiche|affichez|envoie|envoyez|divulgue|divulguez|transmets|transmettez|"
            r"recopie|recopiez)\b[^.\n]{0,40}\b(prompt système|tes instructions|vos instructions|clés? d'api|"
            r"mots? de passe|secrets?|identifiants|jetons? d'accès)\b",
        ),
    ),
    _Rule(
        "EXFILTRATION_LINK",
        "Lien d'exfiltration (image ou URL paramétrée)",
        0.6,
        _rx(
            r"!\[[^\]]*\]\(\s*https?://[^)\s]+\?[^)\s]*=",
            r"https?://[^\s)\"']*(\{\{|\{[a-z_]+\}|%7B|\$\{|\[(data|secret|conversation)\])",
            r"\b(send|post|forward|upload|append)\b[^.\n]{0,40}\b(to|vers)\s+https?://",
            r"\b(envoie|envoyez|transmets|transmettez|ajoute|ajoutez)\b[^.\n]{0,50}\b(à|vers|dans)\s+"
            r"(l'url\s+)?https?://",
        ),
    ),
    _Rule(
        "SUSPICIOUS_ENCODING",
        "Balise ou encodage suspect",
        0.3,
        _rx(
            r"<\s*script\b",
            r"\bjavascript:",
            r"data:[a-z/+-]+;base64,",
            r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{160,}={0,2}(?![A-Za-z0-9+/])",
            r"[‪-‮⁦-⁩]",
        ),
    ),
    _Rule(
        "UNICODE_TAGS",
        "Caractères Unicode invisibles de balisage",
        0.6,
        _rx(r"[\U000E0000-\U000E007F]{3,}"),
    ),
)

_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿­]")
#: Minimum zero-width characters to raise the hidden-text signal (one stray BOM is common).
ZERO_WIDTH_MIN = 3
HIDDEN_TEXT = ("HIDDEN_TEXT", "Texte caché (caractères invisibles ou CSS masqué)", 0.4)

_HIDDEN_HTML = re.compile(
    r"<(?P<tag>[a-z][a-z0-9]*)\b[^>]*style\s*=\s*[\"'][^\"']*(display\s*:\s*none|visibility\s*:\s*hidden|"
    r"font-size\s*:\s*0(?:px|pt|em)?\s*[;\"']|opacity\s*:\s*0(?:\.0+)?\s*[;\"']|color\s*:\s*(?:#fff(?:fff)?|white)\b)"
    r"[^\"']*[\"'][^>]*>(?P<body>.*?)</(?P=tag)\s*>",
    _I | re.DOTALL,
)
_HTML_COMMENT = re.compile(r"<!--(?P<body>.*?)-->", re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@dataclass(slots=True)
class HiddenSignals:
    """Hidden-text evidence found in the *raw* content (before normalisation strips it)."""

    zero_width: int = 0
    snippets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InjectionResult:
    score: float = 0.0
    reasons: list[dict[str, Any]] = field(default_factory=list)

    @property
    def quarantined(self) -> bool:
        return settings.injection_detection and self.score >= settings.injection_threshold


def _excerpt(text: str, start: int, end: int) -> str:
    lo, hi = max(0, start - 20), min(len(text), end + 40)
    return _WS.sub(" ", _ZERO_WIDTH.sub("", text[lo:hi])).strip()[:160]


def scan_hidden(raw: str | None) -> HiddenSignals:
    """Zero-width characters and CSS-hidden / commented text of a raw (HTML, Markdown, text) payload."""
    signals = HiddenSignals()
    if not raw:
        return signals
    signals.zero_width = len(_ZERO_WIDTH.findall(raw))
    for rx in (_HIDDEN_HTML, _HTML_COMMENT):
        for m in rx.finditer(raw):
            body = _WS.sub(" ", _TAGS.sub(" ", m.group("body"))).strip()
            if len(body) >= 12:
                signals.snippets.append(body)
    return signals


def _classifier_score(text: str) -> float | None:
    """Optional local classifier hook (``ORBIT_INJECTION_CLASSIFIER=local``); ``None`` when unavailable."""
    if settings.injection_classifier != "local":
        return None
    try:  # pragma: no cover - optional dependency, never installed in CI
        from app.ingestion import injection_model  # type: ignore[attr-defined]

        return float(injection_model.score(text))
    except Exception as exc:  # pragma: no cover
        logger.info("Local injection classifier unavailable (%s): rules only", exc)
        return None


def detect(text: str, hidden: HiddenSignals | None = None) -> InjectionResult:
    """Score ``text`` (one chunk). ``hidden`` carries raw-content evidence of the parent document."""
    result = InjectionResult()
    if not text:
        return result
    remaining = 1.0
    for rule in RULES:
        for pattern in rule.patterns:
            m = pattern.search(text)
            if m:
                remaining *= 1 - rule.weight
                result.reasons.append(
                    {
                        "code": rule.code,
                        "label": rule.label,
                        "weight": rule.weight,
                        "excerpt": _excerpt(text, m.start(), m.end()),
                    }
                )
                break
    zero_width = len(_ZERO_WIDTH.findall(text))
    hidden_hit = zero_width >= ZERO_WIDTH_MIN
    excerpt = "caractères zero-width" if hidden_hit else ""
    if hidden is not None and not hidden_hit:
        flat = _WS.sub(" ", text)
        for snippet in hidden.snippets:
            probe = snippet[:60]
            if probe and probe in flat:
                hidden_hit, excerpt = True, snippet[:160]
                break
        if not hidden_hit and hidden.zero_width >= ZERO_WIDTH_MIN and result.reasons:
            hidden_hit, excerpt = True, f"{hidden.zero_width} caractère(s) zero-width dans le document"
    if hidden_hit:
        code, label, weight = HIDDEN_TEXT
        remaining *= 1 - weight
        result.reasons.append({"code": code, "label": label, "weight": weight, "excerpt": excerpt})
    score = 1 - remaining
    model = _classifier_score(text)
    if model is not None:
        score = max(score, model)
        result.reasons.append(
            {"code": "CLASSIFIER", "label": "Classifieur local", "weight": model, "excerpt": ""}
        )
    result.score = round(min(1.0, max(0.0, score)), 4)
    return result


def summarize(results: Sequence[InjectionResult]) -> str:
    flagged = [r for r in results if r.quarantined]
    if not flagged:
        return "aucune injection détectée"
    noun = "fragment" if len(flagged) == 1 else "fragments"
    return f"{len(flagged)} {noun} en quarantaine (injection de prompt suspectée)"
