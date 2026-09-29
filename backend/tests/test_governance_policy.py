"""Unit tests of the governance rules (ARCHITECTURE §9, reason details in the style of §4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.enums import GOVERNANCE_ORDER, CandidateType, MemoryKind, MemoryScope, ReasonCode, SourceKind
from app.governance import freshness
from app.governance.policy import (
    Candidate,
    ForgetInfo,
    GovernanceContext,
    SupersessionInfo,
    evaluate,
    included_verdict,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
PROJECT = uuid.uuid4()
ME = uuid.uuid4()
OTHER = uuid.uuid4()
FRESHNESS = {
    "document": 365,
    "note": 120,
    "ticket": 90,
    "crm": 180,
    "feedback": 180,
    "agent_trace": 30,
    "url": 180,
}


def ctx(**overrides: Any) -> GovernanceContext:
    values: dict[str, Any] = {
        "project_id": PROJECT,
        "principals": {"project:*", "role:viewer", f"user:{ME}"},
        "clearance": 1,
        "requester_user_id": ME,
        "session_id": None,
        "scopes": set(MemoryScope),
        "source_kinds": None,
        "freshness_days": FRESHNESS,
        "freshness_override_days": None,
        "min_relevance": 0.35,
        "now": NOW,
    }
    values.update(overrides)
    return GovernanceContext(**values)


def chunk(**overrides: Any) -> Candidate:
    values: dict[str, Any] = {
        "candidate_type": CandidateType.chunk,
        "id": str(uuid.uuid4()),
        "title": "Spécification Atlas",
        "text": "L'authentification repose sur OIDC.",
        "classification": 1,
        "acl_principals": ["project:*"],
        "status": "active",
        "date": NOW - timedelta(days=10),
        "score": 0.8,
        "source_kind": SourceKind.document,
        "version": 2,
    }
    values.update(overrides)
    return Candidate(**values)


def memory(**overrides: Any) -> Candidate:
    values: dict[str, Any] = {
        "candidate_type": CandidateType.memory,
        "id": str(uuid.uuid4()),
        "title": "SSO via OIDC",
        "text": "Décision : SSO via OIDC.",
        "classification": 1,
        "acl_principals": ["project:*"],
        "status": "validated",
        "date": NOW - timedelta(days=12),
        "score": 0.82,
        "memory_scope": MemoryScope.project,
        "memory_kind": MemoryKind.decision,
        "lineage_id": uuid.uuid4(),
    }
    values.update(overrides)
    return Candidate(**values)


def code(candidate: Candidate, context: GovernanceContext | None = None) -> ReasonCode | None:
    verdict = evaluate(candidate, context or ctx())
    return verdict.reason_code if verdict else None


def detail(candidate: Candidate, context: GovernanceContext | None = None) -> str:
    verdict = evaluate(candidate, context or ctx())
    assert verdict is not None
    return verdict.reason_detail


def test_governance_order_is_the_documented_one() -> None:
    assert GOVERNANCE_ORDER == (
        ReasonCode.EXCLUDED_FORGOTTEN,
        ReasonCode.EXCLUDED_ACL,
        ReasonCode.EXCLUDED_CLASSIFICATION,
        ReasonCode.EXCLUDED_SCOPE,
        ReasonCode.EXCLUDED_EXPIRED,
        ReasonCode.EXCLUDED_STALE,
        ReasonCode.EXCLUDED_SUPERSEDED,
        ReasonCode.EXCLUDED_LOW_SCORE,
    )


def test_eligible_candidate_passes() -> None:
    assert evaluate(chunk(), ctx()) is None
    assert evaluate(memory(), ctx()) is None


def test_forgotten() -> None:
    c = chunk(status="forgotten", forgotten=ForgetInfo(at=NOW - timedelta(days=1), by="Alice Martin"))
    assert code(c) == ReasonCode.EXCLUDED_FORGOTTEN
    assert detail(c) == "oublié le 28/09/2026 par Alice Martin"


def test_acl_is_redacted() -> None:
    c = chunk(acl_principals=["role:owner"])
    verdict = evaluate(c, ctx())
    assert verdict is not None and verdict.reason_code == ReasonCode.EXCLUDED_ACL and verdict.redact
    assert verdict.reason_detail == "réservé à : propriétaires"
    # Parent document ACL is enforced too.
    assert code(chunk(extra_acls=[["role:editor"]])) == ReasonCode.EXCLUDED_ACL
    assert code(chunk(acl_principals=[f"user:{ME}"])) is None


def test_classification() -> None:
    c = chunk(classification=3)
    verdict = evaluate(c, ctx())
    assert verdict is not None and verdict.redact
    assert verdict.reason_code == ReasonCode.EXCLUDED_CLASSIFICATION
    assert verdict.reason_detail == "C3 > habilitation C1"
    assert code(chunk(classification=2), ctx(clearance=2)) is None


def test_scope_rules() -> None:
    other = memory(
        memory_scope=MemoryScope.user,
        memory_kind=MemoryKind.preference,
        subject_user_id=OTHER,
        acl_principals=[f"user:{OTHER}"],
    )
    verdict = evaluate(other, ctx())
    assert verdict is not None and verdict.reason_code == ReasonCode.EXCLUDED_SCOPE and verdict.redact
    assert verdict.reason_detail == "mémoire utilisateur d'un autre utilisateur"
    mine = memory(
        memory_scope=MemoryScope.user,
        memory_kind=MemoryKind.preference,
        subject_user_id=ME,
        acl_principals=[f"user:{ME}"],
    )
    assert code(mine) is None
    assert detail(memory(), ctx(scopes={MemoryScope.user})) == "portée non demandée (mémoire projet)"
    assert detail(chunk(), ctx(source_kinds={SourceKind.ticket})) == "type de source non demandé (documents)"
    assert detail(chunk(), ctx(include_sources=False)) == "extraits de sources non demandés"
    assert code(mine, ctx(requester_user_id=None)) == ReasonCode.EXCLUDED_SCOPE


def test_expired_short_term() -> None:
    c = memory(
        memory_scope=MemoryScope.short_term,
        memory_kind=MemoryKind.fact,
        status="proposed",
        expires_at=NOW - timedelta(hours=3),
    )
    assert code(c) == ReasonCode.EXCLUDED_EXPIRED
    assert detail(c).startswith("expirée le 29/09/2026")
    assert code(memory(memory_scope=MemoryScope.short_term, expires_at=NOW + timedelta(hours=1))) is None


def test_stale_per_source_kind_and_override() -> None:
    ticket = chunk(source_kind=SourceKind.ticket, date=NOW - timedelta(days=214))
    assert code(ticket) == ReasonCode.EXCLUDED_STALE
    assert detail(ticket) == "214 j > 90 j (tickets)"
    assert code(ticket, ctx(freshness_override_days=365)) is None
    assert (
        detail(chunk(date=NOW - timedelta(days=40)), ctx(freshness_override_days=30))
        == "40 j > 30 j (demandé)"
    )


def test_validated_decisions_are_never_stale() -> None:
    old = memory(date=NOW - timedelta(days=900), provenance_kinds=(SourceKind.ticket,))
    assert code(old) is None
    proposed_fact = memory(
        memory_kind=MemoryKind.fact,
        status="proposed",
        date=NOW - timedelta(days=200),
        provenance_kinds=(SourceKind.ticket,),
    )
    assert detail(proposed_fact) == "200 j > 90 j (tickets)"
    ended = memory(valid_to=NOW - timedelta(days=1))
    assert detail(ended) == "validité échue le 2026-09-28"


def test_superseded_and_obsolete() -> None:
    old_chunk = chunk(
        status="superseded",
        version=1,
        superseded_by=SupersessionInfo(title="Spécification Atlas", version=2, date=NOW - timedelta(days=3)),
    )
    assert code(old_chunk) == ReasonCode.EXCLUDED_SUPERSEDED
    assert detail(old_chunk) == "remplacé par “Spécification Atlas” (v2, 2026-09-26)"
    replaced = memory(
        status="superseded",
        superseded_by=SupersessionInfo(title="SSO via OIDC v2", version=None, date=NOW - timedelta(days=2)),
    )
    assert detail(replaced) == "remplacé par “SSO via OIDC v2” (2026-09-27)"
    obsolete = memory(status="obsolete", status_changed_at=NOW - timedelta(days=4))
    assert detail(obsolete) == "marqué obsolète le 2026-09-25"


def test_low_score() -> None:
    c = chunk(score=0.214)
    assert code(c) == ReasonCode.EXCLUDED_LOW_SCORE
    assert detail(c) == "score 0,21 < seuil 0,35"
    assert code(chunk(score=0.1, pinned=True, pinned_label="spec-atlas@v2")) is None


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {"status": "forgotten", "acl_principals": ["role:owner"], "classification": 3},
            ReasonCode.EXCLUDED_FORGOTTEN,
        ),
        ({"acl_principals": ["role:owner"], "classification": 3}, ReasonCode.EXCLUDED_ACL),
        ({"classification": 3, "source_kind": SourceKind.ticket}, ReasonCode.EXCLUDED_CLASSIFICATION),
        (
            {"source_kind": SourceKind.ticket, "date": NOW - timedelta(days=300), "score": 0.0},
            ReasonCode.EXCLUDED_SCOPE,
        ),
        (
            {"date": NOW - timedelta(days=400), "status": "superseded", "score": 0.0},
            ReasonCode.EXCLUDED_STALE,
        ),
        ({"status": "superseded", "score": 0.0}, ReasonCode.EXCLUDED_SUPERSEDED),
    ],
)
def test_first_blocking_rule_wins(overrides: dict[str, Any], expected: ReasonCode) -> None:
    context = ctx(source_kinds={SourceKind.document})
    assert code(chunk(**overrides), context) == expected


def test_included_verdicts() -> None:
    relevant = included_verdict(memory(score=0.82), NOW)
    assert relevant.reason_code == ReasonCode.INCLUDED_RELEVANT
    assert relevant.reason_detail == "score 0,82 · décision validée · 12 j"
    pinned = included_verdict(memory(pinned=True, pinned_label="spec-atlas@v2"), NOW)
    assert pinned.reason_code == ReasonCode.INCLUDED_PINNED
    assert pinned.reason_detail == "snapshot spec-atlas@v2"


def test_freshness_helpers() -> None:
    assert freshness.age_days(NOW - timedelta(days=90), NOW) == pytest.approx(90)
    assert freshness.decay_score(NOW - timedelta(days=90), NOW) == pytest.approx(0.5, abs=1e-6)
    assert freshness.decay_score(NOW, NOW) == pytest.approx(1.0)
    assert freshness.policy_days(SourceKind.ticket, FRESHNESS) == 90
    assert freshness.policy_days(SourceKind.ticket, FRESHNESS, 10) == 10
