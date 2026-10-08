"""Decisions and action items of meeting transcripts, with speaker attribution (§F1).

A meeting transcript is rendered by :mod:`app.ingestion.meetings` as one ``[hh:mm:ss] Speaker : text``
line per turn (continuation lines keep the turn's speaker). For each turn, only the statements worth
remembering from a conversation are kept — chit-chat would otherwise produce noisy « constraints »:

* **decisions** (« Décision : … », « nous avons décidé … », « on retient … ») with ``decided_by`` = the
  speaker;
* **action items** (« Action : … », « Action pour Bruno : … », « Bruno se charge de … », « je m'en
  occupe », « je vais envoyer … d'ici vendredi ») with ``action_meta`` = ``{owner, due_date, due_text,
  speaker, timestamp}``: the owner is the named person (matched to a speaker when possible) or the speaker
  for first-person commitments; the due date is resolved against the meeting date when stated;
* explicitly labelled statements (« Risque : … », « Contrainte : … », « Besoin : … »).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.enums import MemoryKind
from app.ingestion.meetings import split_turn_line
from app.memory.conflicts import fold
from app.memory.extractor import MAX_STATEMENT_LENGTH, Statement, extract_statements, make_title

_NAME = r"[A-ZÀ-ÝŒ][\w'’\-]*(?:\s+[A-ZÀ-ÝŒ][\w'’\-]*){0,2}"
_ACTION_LABEL = re.compile(
    rf"^(?:actions?|[àa] faire|todo)\s*(?:\((?P<paren>[^)]{{1,60}})\))?\s*(?:pour\s+(?P<pour>{_NAME}))?"
    r"\s*[:：]\s*(?P<body>.+)$",
    re.IGNORECASE,
)
_OWNER_PHRASE = re.compile(
    rf"^(?P<owner>{_NAME})\s+(?:se charge|s['’]occupe|prend l['’]action|est charg[ée]e?|va se charger)"
    r"\s*(?:de\s+|d['’]|du\s+|des\s+)?(?P<body>.+)$"
)
_FIRST_PERSON = re.compile(
    r"^(?:ok,?\s+|d['’]accord,?\s+|alors\s+)?(?:moi,?\s+)?(?:je\s+m['’]en\s+(?:charge|occupe)|"
    r"je\s+(?:me\s+charge|m['’]occupe)\s+(?:de\s+|d['’]|du\s+|des\s+)|je\s+prends\s+l['’]action|"
    r"je\s+(?:vais|enverrai|ferai|pr[ée]parerai|r[ée]digerai|m['’]engage\s+[àa]))\s*(?P<body>.*)$",
    re.IGNORECASE,
)
_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}  # fmt: skip
_WEEKDAYS = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6}
_DUE = re.compile(
    r"\b(?:d['’]ici\s+(?:le\s+|à\s+|a\s+|au\s+)?|avant\s+(?:le\s+)?|pour\s+(?:le\s+)?|au\s+plus\s+tard\s+(?:le\s+)?|"
    r"[ée]ch[ée]ance\s*:?\s*(?:le\s+)?|deadline\s*:?\s*)"
    r"(?P<due>\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{1,2}(?:er)?\s+[a-zéû]+(?:\s+\d{4})?|"
    r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\s+prochain)?|demain|"
    r"la\s+semaine\s+prochaine|fin\s+(?:de\s+la\s+semaine|du\s+mois|de\s+semaine))",
    re.IGNORECASE,
)
_DECISION_TALK = re.compile(
    r"^(?:(?:alors|donc|ok|bon|bref),?\s+)?(?:on|nous)\s+"
    r"(?:retient|retenons|part sur|partons sur|valide|validons|acte|actons)\b"
)


@dataclass(slots=True)
class TurnState:
    """Speaker of the current turn, carried over chunk boundaries."""

    speaker: str | None = None
    timestamp: str | None = None


def parse_meeting_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def resolve_due(text: str, reference: date | None) -> tuple[str | None, str | None]:
    """``(due_date ISO | None, due_text | None)`` of the first deadline stated in ``text``."""
    match = _DUE.search(text)
    if not match:
        return None, None
    raw = match.group("due").strip()
    folded = fold(raw)
    ref = reference or date.today()
    resolved: date | None = None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            resolved = date.fromisoformat(raw)
        elif "/" in raw:
            parts = [int(p) for p in raw.split("/")]
            year = parts[2] if len(parts) == 3 else ref.year
            year = year + 2000 if year < 100 else year
            resolved = date(year, parts[1], parts[0])
            if len(parts) == 2 and resolved < ref:
                resolved = date(year + 1, parts[1], parts[0])
        elif m := re.fullmatch(r"(\d{1,2})(?:er)?\s+([a-z]+)(?:\s+(\d{4}))?", folded):
            month = _MONTHS.get(m.group(2))
            if month is None:
                return None, None  # « pour 2 personnes »: not a date
            year = int(m.group(3)) if m.group(3) else ref.year
            resolved = date(year, month, int(m.group(1)))
            if not m.group(3) and resolved < ref:
                resolved = date(year + 1, month, int(m.group(1)))
        elif folded.split()[0] in _WEEKDAYS:
            delta = (_WEEKDAYS[folded.split()[0]] - ref.weekday()) % 7 or 7
            resolved = ref + timedelta(days=delta)
        elif folded == "demain":
            resolved = ref + timedelta(days=1)
    except ValueError:
        resolved = None
    return (resolved.isoformat() if resolved else None), raw


def _match_speaker(name: str | None, speakers: list[str]) -> str | None:
    """« Bruno » → « Bruno Leroy » when it designates exactly one speaker."""
    if not name:
        return None
    cleaned = " ".join(name.split())
    folded = fold(cleaned)
    matches = [s for s in speakers if fold(s) == folded or fold(s).split()[0] == folded.split()[0]]
    return matches[0] if len(matches) == 1 else cleaned


def detect_action(
    text: str, speaker: str | None, speakers: list[str], reference: date | None
) -> tuple[str, dict[str, str | None]] | None:
    """``(body, action_meta)`` when ``text`` is an action item, else ``None``."""
    sentence = text.strip()
    owner: str | None = None
    body: str | None = None
    label = _ACTION_LABEL.match(sentence)
    if label:
        body = label.group("body")
        named = label.group("pour") or label.group("paren")
        owner = _match_speaker(named, speakers) if named else None
        if owner is None:
            lead = _OWNER_PHRASE.match(body)
            if lead and _match_speaker(lead.group("owner"), speakers) in speakers:
                owner, body = _match_speaker(lead.group("owner"), speakers), lead.group("body")
            elif _FIRST_PERSON.match(body):
                owner = speaker
    elif lead := _OWNER_PHRASE.match(sentence):
        candidate = _match_speaker(lead.group("owner"), speakers)
        if candidate not in speakers and fold(lead.group("owner")).split()[0] in {"on", "il", "elle", "nous"}:
            return None
        owner, body = candidate, lead.group("body")
    elif first := _FIRST_PERSON.match(sentence):
        if not _DUE.search(sentence) and "charge" not in fold(sentence) and "occupe" not in fold(sentence):
            return None  # « je vais regarder » without deadline nor commitment: not an action item
        owner, body = speaker, first.group("body") or sentence
    if body is None:
        return None
    body = body.strip(" :,;-–").rstrip(".")
    nested = _FIRST_PERSON.match(body)
    if nested and nested.group("body"):
        body = nested.group("body").strip(" :,;-–").rstrip(".")
    body = body or sentence
    due_date, due_text = resolve_due(sentence, reference)
    return body, {"owner": owner, "due_date": due_date, "due_text": due_text}


def _action_statement(body: str, meta: dict[str, str | None], line: str, state: TurnState) -> Statement:
    owner = meta.get("owner")
    content = f"Action{f' — {owner}' if owner else ''} : {body[0].upper()}{body[1:]}"
    if meta.get("due_date") or meta.get("due_text"):
        content += f" (échéance : {meta.get('due_date') or meta.get('due_text')})"
    statement = Statement(
        kind=MemoryKind.action,
        title=make_title(body),
        content=content[:MAX_STATEMENT_LENGTH],
        confidence=0.8 if owner else 0.7,
        explicit_decision=False,
        rule="meeting:action",
        quote=line,
    )
    statement.action_meta = {**meta, "speaker": state.speaker, "timestamp": state.timestamp}
    return statement


def extract_meeting_statements(
    text: str,
    speakers: list[str],
    state: TurnState,
    reference: date | None = None,
) -> list[Statement]:
    """Statements of one chunk of a rendered transcript (``state`` is updated across chunks)."""
    statements: list[Statement] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        timestamp, speaker, body = split_turn_line(line, speakers)
        if speaker:
            state.speaker, state.timestamp = speaker, timestamp
        elif fold(line).startswith(("date :", "participants :")):
            continue
        quote = f"[{state.timestamp}] {state.speaker} : {body}" if state.timestamp else line
        for sentence in re.split(r"(?<=[.!?…])\s+", body):
            action = detect_action(sentence, state.speaker, speakers, reference)
            if action is not None:
                statements.append(_action_statement(action[0], action[1], quote, state))
                continue
            if _DECISION_TALK.match(fold(sentence)) and len(sentence) <= MAX_STATEMENT_LENGTH:
                talk = Statement(
                    MemoryKind.decision, make_title(sentence), sentence, 0.7, False, "meeting:decision"
                )
                talk.quote, talk.decided_by = quote, state.speaker
                statements.append(talk)
                continue
            for statement in extract_statements(sentence):
                labelled = statement.rule.startswith("label:")
                if statement.kind != MemoryKind.decision and not labelled:
                    continue  # conversation: only decisions, actions and labelled statements
                statement.quote = quote
                if statement.kind == MemoryKind.decision:
                    statement.decided_by = state.speaker
                statements.append(statement)
    return statements


__all__ = ["TurnState", "detect_action", "extract_meeting_statements", "parse_meeting_date", "resolve_due"]
