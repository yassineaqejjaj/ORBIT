"""All ORBIT enums (docs/ARCHITECTURE.md §4). Imported everywhere, never redefined.

Values are identical to the frontend ``src/lib/enums.ts``. Enums are stored in Postgres as ``text``
with a ``CHECK`` constraint (see :func:`check_in`).

The second part of the module declares the small closed vocabularies that §5 and docs/API.md use
(actor types, relation node types, job step statuses, PII types, ...). They are not part of §4 but
are centralised here for the same reason.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Role(StrEnum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class SourceKind(StrEnum):
    document = "document"
    note = "note"
    ticket = "ticket"
    crm = "crm"
    feedback = "feedback"
    agent_trace = "agent_trace"
    url = "url"


class DocumentStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    indexed = "indexed"
    failed = "failed"
    forgotten = "forgotten"


class ChunkStatus(StrEnum):
    active = "active"
    superseded = "superseded"
    forgotten = "forgotten"


class JobKind(StrEnum):
    ingest = "ingest"
    reindex = "reindex"
    forget = "forget"
    consolidate = "consolidate"
    extract_memory = "extract_memory"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    #: Dead letter: retries exhausted or poison pill (worker crashed repeatedly on the job).
    dead = "dead"
    cancelled = "cancelled"


class MemoryScope(StrEnum):
    short_term = "short_term"
    project = "project"
    user = "user"
    long_term = "long_term"


class MemoryKind(StrEnum):
    decision = "decision"
    requirement = "requirement"
    constraint = "constraint"
    fact = "fact"
    preference = "preference"
    summary = "summary"
    risk = "risk"


class MemoryStatus(StrEnum):
    proposed = "proposed"
    validated = "validated"
    superseded = "superseded"
    obsolete = "obsolete"
    forgotten = "forgotten"


class MemoryEventType(StrEnum):
    created = "created"
    edited = "edited"
    validated = "validated"
    superseded = "superseded"
    obsoleted = "obsoleted"
    forgotten = "forgotten"
    restored = "restored"
    conflict_detected = "conflict_detected"


class RelationType(StrEnum):
    supersedes = "supersedes"
    contradicts = "contradicts"
    derived_from = "derived_from"
    mentions = "mentions"
    constrains = "constrains"
    relates_to = "relates_to"


class CandidateType(StrEnum):
    chunk = "chunk"
    memory = "memory"
    session = "session"


class Intent(StrEnum):
    general = "general"
    specification = "specification"
    design = "design"
    engineering = "engineering"
    research = "research"
    analysis = "analysis"
    validation = "validation"


class ReasonCode(StrEnum):
    INCLUDED_RELEVANT = "INCLUDED_RELEVANT"
    INCLUDED_PINNED = "INCLUDED_PINNED"
    EXCLUDED_ACL = "EXCLUDED_ACL"
    EXCLUDED_CLASSIFICATION = "EXCLUDED_CLASSIFICATION"
    EXCLUDED_SCOPE = "EXCLUDED_SCOPE"
    EXCLUDED_STALE = "EXCLUDED_STALE"
    EXCLUDED_EXPIRED = "EXCLUDED_EXPIRED"
    EXCLUDED_SUPERSEDED = "EXCLUDED_SUPERSEDED"
    EXCLUDED_CONFLICT = "EXCLUDED_CONFLICT"
    EXCLUDED_DUPLICATE = "EXCLUDED_DUPLICATE"
    EXCLUDED_LOW_SCORE = "EXCLUDED_LOW_SCORE"
    EXCLUDED_BUDGET = "EXCLUDED_BUDGET"
    EXCLUDED_FORGOTTEN = "EXCLUDED_FORGOTTEN"

    @property
    def is_included(self) -> bool:
        return self.value.startswith("INCLUDED_")

    @property
    def label(self) -> str:
        return REASON_CODE_LABELS[self]


class AgentKind(StrEnum):
    product = "product"
    design = "design"
    engineering = "engineering"
    research = "research"
    custom = "custom"


class Classification(IntEnum):
    """Classification levels (ARCHITECTURE §3)."""

    C0 = 0
    C1 = 1
    C2 = 2
    C3 = 3

    @property
    def code(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        return CLASSIFICATION_LABELS[int(self)]


# --- Vocabularies used by §5 / API.md -------------------------------------------------------------


class ActorType(StrEnum):
    user = "user"
    agent = "agent"
    system = "system"


class PrincipalKind(StrEnum):
    user = "user"
    agent = "agent"


class RelationNodeType(StrEnum):
    chunk = "chunk"
    memory = "memory"
    document = "document"


class TombstoneTarget(StrEnum):
    document = "document"
    memory = "memory"
    chunk = "chunk"


class ContextRequestStatus(StrEnum):
    succeeded = "succeeded"
    failed = "failed"


class JobStepStatus(StrEnum):
    ok = "ok"
    failed = "failed"
    skipped = "skipped"


#: Names of the ``ingest`` pipeline steps, in order (``JobStep.name``; other names are allowed).
PIPELINE_STEPS: tuple[str, ...] = ("extract", "pii", "classify", "chunk", "embed", "index", "extract_memory")


class PiiType(StrEnum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    IBAN = "IBAN"
    CARD = "CARD"
    NIR = "NIR"
    IP = "IP"
    PERSON = "PERSON"


class FeedbackFlag(StrEnum):
    irrelevant = "irrelevant"
    outdated = "outdated"
    wrong = "wrong"


class TurnRole(StrEnum):
    user = "user"
    agent = "agent"
    tool = "tool"


class AlertLevel(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


# --- Labels & helpers -----------------------------------------------------------------------------

REASON_CODE_LABELS: dict[ReasonCode, str] = {
    ReasonCode.INCLUDED_RELEVANT: "Retenu — pertinent",
    ReasonCode.INCLUDED_PINNED: "Retenu — hérité du snapshot",
    ReasonCode.EXCLUDED_ACL: "Exclu — accès non autorisé",
    ReasonCode.EXCLUDED_CLASSIFICATION: "Exclu — classification trop élevée",
    ReasonCode.EXCLUDED_SCOPE: "Exclu — hors périmètre demandé",
    ReasonCode.EXCLUDED_STALE: "Exclu — information périmée",
    ReasonCode.EXCLUDED_EXPIRED: "Exclu — mémoire court terme expirée",
    ReasonCode.EXCLUDED_SUPERSEDED: "Exclu — remplacé",
    ReasonCode.EXCLUDED_CONFLICT: "Exclu — contradiction résolue",
    ReasonCode.EXCLUDED_DUPLICATE: "Exclu — doublon",
    ReasonCode.EXCLUDED_LOW_SCORE: "Exclu — pertinence insuffisante",
    ReasonCode.EXCLUDED_BUDGET: "Exclu — budget de tokens atteint",
    ReasonCode.EXCLUDED_FORGOTTEN: "Exclu — oubli sélectif",
}

#: Reason codes whose details must be redacted for callers without access (non-leak principle, §3).
REDACTED_REASON_CODES: frozenset[ReasonCode] = frozenset(
    {ReasonCode.EXCLUDED_ACL, ReasonCode.EXCLUDED_CLASSIFICATION}
)

#: Governance evaluation order (§9 step 5): first blocking reason wins.
GOVERNANCE_ORDER: tuple[ReasonCode, ...] = (
    ReasonCode.EXCLUDED_FORGOTTEN,
    ReasonCode.EXCLUDED_ACL,
    ReasonCode.EXCLUDED_CLASSIFICATION,
    ReasonCode.EXCLUDED_SCOPE,
    ReasonCode.EXCLUDED_EXPIRED,
    ReasonCode.EXCLUDED_STALE,
    ReasonCode.EXCLUDED_SUPERSEDED,
    ReasonCode.EXCLUDED_LOW_SCORE,
)

CLASSIFICATION_LABELS: dict[int, str] = {0: "Public", 1: "Interne", 2: "Confidentiel", 3: "Secret"}
CLASSIFICATION_CODES: dict[int, str] = {0: "C0", 1: "C1", 2: "C2", 3: "C3"}
#: Levels that trigger the UI warning banner and API ``warnings`` (§3).
RESTRICTED_CLASSIFICATION_MIN = 2

ROLE_RANK: dict[Role, int] = {Role.viewer: 0, Role.editor: 1, Role.owner: 2}

ROLE_LABELS: dict[Role, str] = {Role.owner: "Propriétaire", Role.editor: "Éditeur", Role.viewer: "Lecteur"}

SOURCE_KIND_LABELS: dict[SourceKind, str] = {
    SourceKind.document: "Document",
    SourceKind.note: "Note",
    SourceKind.ticket: "Ticket",
    SourceKind.crm: "CRM",
    SourceKind.feedback: "Retour client",
    SourceKind.agent_trace: "Trace d'agent",
    SourceKind.url: "Page web",
}

MEMORY_KIND_LABELS: dict[MemoryKind, str] = {
    MemoryKind.decision: "Décision",
    MemoryKind.requirement: "Besoin",
    MemoryKind.constraint: "Contrainte",
    MemoryKind.fact: "Fait",
    MemoryKind.preference: "Préférence",
    MemoryKind.summary: "Synthèse",
    MemoryKind.risk: "Risque",
}

PII_LABELS: dict[PiiType, str] = {
    PiiType.EMAIL: "[EMAIL]",
    PiiType.PHONE: "[TÉLÉPHONE]",
    PiiType.IBAN: "[IBAN]",
    PiiType.CARD: "[CARTE]",
    PiiType.NIR: "[NIR]",
    PiiType.IP: "[IP]",
    PiiType.PERSON: "[PERSONNE]",
}


def classification_code(level: int) -> str:
    """``2 -> "C2"``."""
    return CLASSIFICATION_CODES.get(int(level), f"C{level}")


def classification_label(level: int) -> str:
    """``2 -> "Confidentiel"``."""
    return CLASSIFICATION_LABELS.get(int(level), "Inconnu")


def classification_warning(level: int) -> str | None:
    """French warning sentence for restricted levels (C2/C3), ``None`` otherwise."""
    if int(level) < RESTRICTED_CLASSIFICATION_MIN:
        return None
    return (
        f"Le contexte contient des informations classifiées {classification_code(level)} "
        f"({classification_label(level)})."
    )


def role_at_least(role: Role | str | None, minimum: Role | str) -> bool:
    """True when ``role`` is ``minimum`` or a superset of it (owner ⊃ editor ⊃ viewer)."""
    if role is None:
        return False
    return ROLE_RANK[Role(role)] >= ROLE_RANK[Role(minimum)]


def values(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum_cls)


def check_in(column: str, enum_cls: type[StrEnum]) -> str:
    """SQL ``CHECK`` expression restricting ``column`` to the enum values."""
    allowed = ", ".join(f"'{v}'" for v in values(enum_cls))
    return f"{column} IN ({allowed})"
