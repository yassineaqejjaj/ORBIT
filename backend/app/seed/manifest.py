"""Demo data manifest: loading, relative-date rendering and validation.

``data/manifest.json`` describes everything the seed creates (users, project, agents, sources, documents,
memory, sessions, context requests). Data files never contain absolute dates: they use tokens that are
resolved against the execution date J so the demo is always « fresh » :

* ``{{J-56}}``      → ISO 8601 datetime (JSON / CSV imports, parsed by the importers);
* ``{{date:J-56}}`` → French long date (« 4 août 2026 ») for Markdown documents.

Everything here is pure (no network, no database) so it is unit-tested by ``tests/test_seed_data.py``.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

from app.enums import AgentKind, FeedbackFlag, Intent, MemoryKind, MemoryScope, Role, SourceKind

DATA_DIR = Path(__file__).resolve().parent / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"

MIN_WORDS = 150
MAX_WORDS = 900
BUSINESS_HOUR = 9

_TOKEN = re.compile(r"\{\{(?:(?P<fmt>date):)?J-(?P<days>\d{1,4})\}\}")
_WORD = re.compile(r"[\wÀ-ÿ’'-]+", re.UNICODE)
FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


# --------------------------------------------------------------------------------------------------
# Dates


def day_at(now: datetime, days_ago: int, hour: int = BUSINESS_HOUR, minute: int = 0) -> datetime:
    """``now - days_ago`` at a business hour (UTC), never in the future."""
    base = (now - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    latest = now - timedelta(minutes=1)
    return min(base, latest)


def french_date(value: datetime) -> str:
    day = "1er" if value.day == 1 else str(value.day)
    return f"{day} {FRENCH_MONTHS[value.month - 1]} {value.year}"


def render(text: str, now: datetime) -> str:
    """Replace every ``{{J-n}}`` / ``{{date:J-n}}`` token with a date relative to ``now``."""

    def _sub(match: re.Match[str]) -> str:
        when = day_at(now, int(match.group("days")))
        return french_date(when) if match.group("fmt") == "date" else when.isoformat()

    return _TOKEN.sub(_sub, text)


def token_offsets(text: str) -> list[int]:
    """Offsets (days before J) referenced by the tokens of ``text``."""
    return [int(m.group("days")) for m in _TOKEN.finditer(text)]


def word_count(text: str) -> int:
    return len(_WORD.findall(_TOKEN.sub("", text)))


# --------------------------------------------------------------------------------------------------
# Loading


@cache
def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def data_path(relative: str) -> Path:
    path = (DATA_DIR / relative).resolve()
    if DATA_DIR not in path.parents:
        raise ValueError(f"Chemin de données hors du dossier du seed : {relative}")
    return path


def raw_document_text(doc: dict[str, Any]) -> str:
    """Unrendered text of a ``mode: text`` document (``append`` concatenates a second file)."""
    text = data_path(doc["file"]).read_text(encoding="utf-8")
    if doc.get("append"):
        text = text.rstrip() + "\n\n" + data_path(doc["append"]).read_text(encoding="utf-8")
    return text


def document_text(doc: dict[str, Any], now: datetime) -> str:
    return render(raw_document_text(doc), now)


def import_file(doc: dict[str, Any], now: datetime) -> tuple[str, bytes, str]:
    """``(filename, rendered bytes, content type)`` of a ``mode: import`` document."""
    path = data_path(doc["file"])
    content = render(path.read_text(encoding="utf-8"), now).encode("utf-8")
    content_type = "text/csv" if path.suffix.lower() == ".csv" else "application/json"
    return path.name, content, content_type


def import_records(doc: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """Parsed records of an import file (rendered when ``now`` is given, raw tokens otherwise)."""
    path = data_path(doc["file"])
    text = path.read_text(encoding="utf-8")
    if now is not None:
        text = render(text, now)
    if path.suffix.lower() == ".csv":
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"{doc['file']} : un tableau JSON est attendu")
    return data


def record_external_id(record: dict[str, Any]) -> str | None:
    for key in ("id", "external_id", "key", "ticket_id"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def by_key(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["key"]: item for item in items}


def phases(manifest: dict[str, Any]) -> list[int]:
    return sorted({int(doc.get("phase", 1)) for doc in manifest["documents"]})


def expected_counts(manifest: dict[str, Any]) -> dict[str, int]:
    """Number of documents, sources and records the manifest produces (used by the summary)."""
    documents = 0
    for doc in manifest["documents"]:
        if doc["mode"] == "import":
            documents += int(doc["records"])
        elif int(doc.get("version", 1)) == 1:
            documents += 1
    return {"sources": len(manifest["sources"]), "documents": documents}


# --------------------------------------------------------------------------------------------------
# Validation


def _enum_ok(enum: type[StrEnum], value: Any) -> bool:
    try:
        enum(value)
    except ValueError:
        return False
    return True


def validate_manifest(manifest: dict[str, Any] | None = None) -> list[str]:
    """Return the list of problems (French messages); empty when the data set is coherent."""
    m = manifest if manifest is not None else load_manifest()
    errors: list[str] = []

    users = by_key(m["users"])
    agents = by_key(m["agents"])
    sources = by_key(m["sources"])
    for section in ("users", "agents", "sources", "documents", "memory"):
        keys = [item["key"] for item in m[section]]
        if len(keys) != len(set(keys)):
            errors.append(f"Clés en double dans « {section} »")

    for user in m["users"]:
        if not _enum_ok(Role, user["role"]) or not 0 <= int(user["clearance"]) <= 3:
            errors.append(f"Utilisateur {user['key']} : rôle ou habilitation invalide")
        if not user["email"].endswith("@nordalis.example"):
            errors.append(f"Utilisateur {user['key']} : domaine fictif nordalis.example attendu")
    if m["project"]["owner"] not in users:
        errors.append("Propriétaire du projet inconnu")

    for agent in m["agents"]:
        if not _enum_ok(AgentKind, agent["kind"]):
            errors.append(f"Agent {agent['key']} : type invalide")
        if agent["acts_for"] not in users:
            errors.append(f"Agent {agent['key']} : utilisateur « {agent['acts_for']} » inconnu")

    for source in m["sources"]:
        if not _enum_ok(SourceKind, source["kind"]):
            errors.append(f"Source {source['key']} : type invalide")
        if not 0 <= int(source["default_classification"]) <= 3:
            errors.append(f"Source {source['key']} : classification invalide")

    seen_versions: dict[tuple[str, str], int] = {}
    for doc in m["documents"]:
        key = doc["key"]
        if doc["source"] not in sources:
            errors.append(f"Document {key} : source « {doc['source']} » inconnue")
            continue
        try:
            path = data_path(doc["file"])
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file():
            errors.append(f"Document {key} : fichier manquant {doc['file']}")
            continue
        if doc.get("append") and not data_path(doc["append"]).is_file():
            errors.append(f"Document {key} : fichier ajouté manquant {doc['append']}")
            continue
        if doc["mode"] == "text":
            text = raw_document_text(doc)
            words = word_count(text)
            if not MIN_WORDS <= words <= MAX_WORDS:
                errors.append(f"Document {key} : {words} mots (attendu {MIN_WORDS}–{MAX_WORDS})")
            if int(doc["offset_days"]) <= 0:
                errors.append(f"Document {key} : offset_days doit être positif")
            if not 0 <= int(doc["classification"]) <= 3:
                errors.append(f"Document {key} : classification invalide")
            version = int(doc.get("version", 1))
            ident = (doc["source"], doc["external_id"])
            previous = seen_versions.get(ident, 0)
            if version != previous + 1:
                errors.append(f"Document {key} : version {version} inattendue (précédente : {previous})")
            seen_versions[ident] = version
        elif doc["mode"] == "import":
            if doc["source_kind"] != sources[doc["source"]]["kind"]:
                errors.append(f"Import {key} : type de source incohérent")
            try:
                records = import_records(doc)
            except (ValueError, csv.Error) as exc:
                errors.append(f"Import {key} : fichier illisible ({exc})")
                continue
            if len(records) != int(doc["records"]):
                errors.append(f"Import {key} : {len(records)} enregistrements (attendu {doc['records']})")
            ids = [record_external_id(r) for r in records]
            if None in ids or len(set(ids)) != len(ids):
                errors.append(f"Import {key} : identifiants manquants ou en double")
            offsets = token_offsets(path.read_text(encoding="utf-8"))
            if len(offsets) != len(records):
                errors.append(f"Import {key} : chaque enregistrement doit porter une date relative")
            elif offsets:
                low, high = doc["offset_days_range"]
                if min(offsets) != int(low) or max(offsets) != int(high):
                    errors.append(
                        f"Import {key} : dates {min(offsets)}–{max(offsets)} (attendu {low}–{high})"
                    )
                stale = doc.get("stale_records")
                if stale is not None and sum(1 for o in offsets if o > 90) != int(stale):
                    errors.append(f"Import {key} : {stale} enregistrements de plus de 90 jours attendus")
        else:
            errors.append(f"Document {key} : mode inconnu {doc['mode']}")

    for rule in m.get("validations", []):
        if not _enum_ok(MemoryKind, rule["kind"]):
            errors.append(f"Validation {rule['contains']} : type de mémoire invalide")
        if int(rule["after_phase"]) not in phases(m):
            errors.append(f"Validation {rule['contains']} : phase inconnue")

    for item in m["memory"]:
        if not _enum_ok(MemoryScope, item["scope"]) or not _enum_ok(MemoryKind, item["kind"]):
            errors.append(f"Mémoire {item['key']} : portée ou type invalide")
            continue
        scope = MemoryScope(item["scope"])
        if item.get("org") and scope != MemoryScope.long_term:
            errors.append(f"Mémoire {item['key']} : seule la mémoire long terme peut être organisationnelle")
        if scope == MemoryScope.user and item.get("subject") not in users:
            errors.append(f"Mémoire {item['key']} : sujet inconnu")
        if scope == MemoryScope.short_term and not item.get("session_id"):
            errors.append(f"Mémoire {item['key']} : session_id requis")
        for actor_key, pool in (("as_user", users), ("as_agent", agents)):
            if item.get(actor_key) and item[actor_key] not in pool:
                errors.append(f"Mémoire {item['key']} : acteur « {item[actor_key]} » inconnu")
        forget = item.get("forget")
        if forget and (forget.get("as_user") not in users or not forget.get("reason")):
            errors.append(f"Mémoire {item['key']} : oubli sans justification ou acteur inconnu")

    for session in m["sessions"]:
        if session["agent"] not in agents or not session["turns"]:
            errors.append(f"Session {session['id']} : agent inconnu ou aucun tour")

    saved: set[str] = set()
    for index, req in enumerate(m["context_requests"], start=1):
        label = f"Requête {index}"
        if req["agent"] not in agents or req["user"] not in users:
            errors.append(f"{label} : agent ou utilisateur inconnu")
        if req["via"] not in ("agent", "user"):
            errors.append(f"{label} : « via » doit valoir agent ou user")
        if req.get("intent") and not _enum_ok(Intent, req["intent"]):
            errors.append(f"{label} : intention invalide")
        if not 0 <= int(req["day_offset"]) <= 13 or not 0 <= int(req["hour"]) <= 23:
            errors.append(f"{label} : horodatage hors des 14 derniers jours")
        base = req.get("base_snapshot")
        if base and base["name"] not in saved:
            errors.append(f"{label} : snapshot de base « {base['name']} » jamais enregistré avant")
        if req.get("save_snapshot"):
            saved.add(req["save_snapshot"])
        feedback = req.get("feedback")
        if feedback and not 1 <= int(feedback["rating"]) <= 5:
            errors.append(f"{label} : note de feedback invalide")
    if "outdated" not in {flag.value for flag in FeedbackFlag}:
        errors.append("Drapeau de feedback « outdated » introuvable")

    return errors


def now_utc() -> datetime:
    return datetime.now(UTC)
