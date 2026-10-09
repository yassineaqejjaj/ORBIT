"""Change event types and their French labels (docs/FEATURES.md F2)."""

from __future__ import annotations

from enum import StrEnum


class ChangeType(StrEnum):
    memory_created = "memory.created"
    memory_validated = "memory.validated"
    memory_superseded = "memory.superseded"
    memory_obsoleted = "memory.obsoleted"
    memory_forgotten = "memory.forgotten"
    memory_conflict_detected = "memory.conflict_detected"
    memory_conflict_resolved = "memory.conflict_resolved"
    document_ingested = "document.ingested"
    document_new_version = "document.new_version"
    document_forgotten = "document.forgotten"
    document_stale = "document.stale"
    snapshot_created = "snapshot.created"
    connector_synced = "connector.synced"
    context_served = "context.served"


CHANGE_TYPE_LABELS: dict[str, str] = {
    ChangeType.memory_created: "Nouvelle décision ou contrainte",
    ChangeType.memory_validated: "Mémoire validée",
    ChangeType.memory_superseded: "Mémoire remplacée",
    ChangeType.memory_obsoleted: "Mémoire obsolète",
    ChangeType.memory_forgotten: "Mémoire oubliée",
    ChangeType.memory_conflict_detected: "Contradiction détectée",
    ChangeType.memory_conflict_resolved: "Contradiction arbitrée",
    ChangeType.document_ingested: "Document ingéré",
    ChangeType.document_new_version: "Nouvelle version de document",
    ChangeType.document_forgotten: "Document oublié",
    ChangeType.document_stale: "Document périmé",
    ChangeType.snapshot_created: "Snapshot enregistré",
    ChangeType.connector_synced: "Connecteur synchronisé",
    ChangeType.context_served: "Contexte servi",
}

#: Types a webhook only receives when explicitly selected (an empty selection = every *other* type).
OPT_IN_TYPES: frozenset[str] = frozenset({ChangeType.context_served.value})

ALL_TYPES: tuple[str, ...] = tuple(t.value for t in ChangeType)
#: Pseudo-type of webhook test deliveries.
PING_TYPE = "ping"


def type_label(value: str) -> str:
    return CHANGE_TYPE_LABELS.get(value, value)


def normalize_types(values: list[str] | None) -> list[str]:
    """Deduplicated known types (``ValueError`` on an unknown one)."""
    result: list[str] = []
    for value in values or []:
        value = value.strip()
        if value not in ALL_TYPES:
            raise ValueError(f"Type de changement inconnu : {value}")
        if value not in result:
            result.append(value)
    return result
