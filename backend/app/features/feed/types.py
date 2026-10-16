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
    #: Revocation events (NOV-80): access to something was withdrawn, derived artifacts must be invalidated.
    document_acl_changed = "document.acl_changed"
    memory_acl_changed = "memory.acl_changed"
    document_classification_changed = "document.classification_changed"
    member_removed = "member.removed"
    agent_revoked = "agent.revoked"


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
    ChangeType.document_acl_changed: "Accès au document modifié",
    ChangeType.memory_acl_changed: "Accès à une mémoire modifié",
    ChangeType.document_classification_changed: "Classification du document modifiée",
    ChangeType.member_removed: "Membre retiré du projet",
    ChangeType.agent_revoked: "Clé d'agent révoquée",
}

#: Types a webhook only receives when explicitly selected (an empty selection = every *other* type).
OPT_IN_TYPES: frozenset[str] = frozenset({ChangeType.context_served.value})

#: Events telling a consumer to invalidate what it derived from a source whose access was withdrawn. Their
#: webhook payload is minimal (ids, restricted flag, classification levels, ``effective_at``).
REVOCATION_TYPES: frozenset[str] = frozenset(
    {
        ChangeType.document_acl_changed.value,
        ChangeType.memory_acl_changed.value,
        ChangeType.document_classification_changed.value,
        ChangeType.member_removed.value,
        ChangeType.agent_revoked.value,
    }
)
#: Types a webhook only receives when explicitly selected: existing subscribers with an empty selection
#: (« every other type ») keep receiving exactly what they received before. The feed shows all of them.
WEBHOOK_OPT_IN_TYPES: frozenset[str] = OPT_IN_TYPES | REVOCATION_TYPES

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
