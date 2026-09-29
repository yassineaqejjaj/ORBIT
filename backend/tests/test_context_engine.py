"""Unit tests of the context engine stages (no infrastructure: pure functions and fakes)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.context import compression, packaging, persistence, selection
from app.context import snapshots as snapshot_service
from app.context.selection import Decision
from app.context.visibility import FORGOTTEN_TEXT, RESTRICTED_TITLE, Viewer, redact_markdown
from app.enums import CandidateType, Intent, MemoryKind, MemoryScope, ReasonCode, SourceKind
from app.errors import ApiError
from app.governance.policy import Candidate, GovernanceContext, Verdict, evaluate, included_verdict
from app.models import ContextSnapshot
from app.schemas import Scores, SnapshotItem

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
ME = uuid.uuid4()
BOB = uuid.uuid4()
LOREM = (
    "L'authentification Atlas repose sur OIDC avec le fournisseur d'identité interne. "
    "Les jetons sont signés en RS256 et renouvelés toutes les quinze minutes. "
    "Le portail client conserve une session de trente minutes. "
)


def cand(kind: CandidateType = CandidateType.chunk, **overrides: Any) -> Candidate:
    values: dict[str, Any] = {
        "candidate_type": kind,
        "id": str(uuid.uuid4()),
        "title": "Spécification Atlas",
        "text": LOREM,
        "classification": 1,
        "acl_principals": ["project:*"],
        "status": "validated" if kind == CandidateType.memory else "active",
        "date": NOW - timedelta(days=12),
        "score": 0.8,
        "tokens": 40,
    }
    if kind == CandidateType.chunk:
        values.update(source_kind=SourceKind.document, version=2, uri="https://wiki.example/atlas")
    if kind == CandidateType.memory:
        values.update(
            memory_scope=MemoryScope.project, memory_kind=MemoryKind.decision, lineage_id=uuid.uuid4()
        )
    values.update(overrides)
    return Candidate(**values)


def viewer(**overrides: Any) -> Viewer:
    values: dict[str, Any] = {
        "principals": frozenset({"project:*", "role:viewer", f"user:{ME}"}),
        "clearance": 1,
        "user_id": ME,
        "sees_restricted_details": False,
        "is_admin": False,
    }
    values.update(overrides)
    return Viewer(**values)


# --- Selection ------------------------------------------------------------------------------------------


def test_conflict_validated_beats_proposed_even_if_more_relevant() -> None:
    validated = cand(CandidateType.memory, title="SSO via OIDC", text="Décision : SSO via OIDC.", score=0.6)
    proposed = cand(
        CandidateType.memory,
        title="SSO par mot de passe",
        text="Mot de passe local.",
        status="proposed",
        score=0.9,
    )
    result = selection.select_candidates(
        [validated, proposed], token_budget=4000, now=NOW, contradictions=[(validated.key, proposed.key)]
    )
    assert [d.candidate.key for d in result.included] == [validated.key]
    (loser,) = result.excluded
    assert loser.verdict.reason_code == ReasonCode.EXCLUDED_CONFLICT
    assert loser.verdict.reason_detail == "contredit par une source validée : “SSO via OIDC”"
    assert loser.related is validated


def test_conflict_between_equals_newer_wins() -> None:
    old = cand(CandidateType.memory, title="Ancienne", text="Durée 30 min.", date=NOW - timedelta(days=90))
    new = cand(CandidateType.memory, title="Nouvelle", text="Durée 15 min.", date=NOW - timedelta(days=2))
    losers = selection.resolve_conflicts([old, new], [(old.key, new.key)])
    assert list(losers) == [old.key]
    assert losers[old.key][1] == "contredit par une source plus récente : “Nouvelle” (2026-09-27)"


def test_duplicates_lexical_and_embedding() -> None:
    first = cand(score=0.9)
    copy = cand(title="Copie", score=0.7)
    result = selection.select_candidates([copy, first], token_budget=4000, now=NOW)
    dup = next(d for d in result.excluded if d.verdict.reason_code == ReasonCode.EXCLUDED_DUPLICATE)
    assert dup.candidate is copy and dup.related is first
    a = cand(text="Texte A totalement différent", embedding=[1.0, 0.0, 0.0])
    b = cand(text="Autre formulation sans mots communs", embedding=[0.99, 0.05, 0.0])
    assert selection.find_duplicates([a, b]) == {b.key: a}


def test_priority_tiers_order_the_package() -> None:
    items = [
        cand(CandidateType.session, title="tour", text="Question de l'utilisateur sur Atlas.", score=0.99),
        cand(score=0.95, text="Extrait de source sur Atlas et ses jetons de session."),
        cand(
            CandidateType.memory,
            memory_kind=MemoryKind.preference,
            text="Préférence de thème sombre.",
            score=0.9,
        ),
        cand(
            CandidateType.memory, memory_kind=MemoryKind.risk, text="Risque de fuite des jetons.", score=0.9
        ),
        cand(
            CandidateType.memory,
            memory_kind=MemoryKind.requirement,
            text="Besoin de connexion unique.",
            score=0.9,
        ),
        cand(
            CandidateType.memory,
            memory_kind=MemoryKind.constraint,
            text="Contrainte RGPD stricte.",
            score=0.5,
        ),
    ]
    result = selection.select_candidates(items, token_budget=4000, now=NOW)
    tiers = [selection.priority_tier(d.candidate) for d in result.included]
    assert tiers == sorted(tiers)
    assert result.included[0].candidate.memory_kind == MemoryKind.constraint


def test_budget_fill_excludes_with_detail() -> None:
    big = [cand(text=f"{LOREM} Variante {i} " * 8, tokens=400, score=0.9 - i / 100) for i in range(8)]
    # Distinct texts so none is a duplicate of another.
    for i, c in enumerate(big):
        c.text = f"Document {i} : " + " ".join(f"mot{i}_{j}" for j in range(300))
    result = selection.select_candidates(big, token_budget=500, now=NOW)
    over = [d for d in result.excluded if d.verdict.reason_code == ReasonCode.EXCLUDED_BUDGET]
    assert result.included and over
    assert all("budget restant" in d.verdict.reason_detail for d in over)
    assert sum(d.allowance for d in result.included) < 500


# --- Compression & packaging ------------------------------------------------------------------------------


def _included(*candidates: Candidate, allowance: int = 200) -> list[Decision]:
    return [Decision(candidate=c, verdict=included_verdict(c, NOW), allowance=allowance) for c in candidates]


def test_compress_text_extracts_relevant_sentences_within_allowance() -> None:
    text = "Introduction générale. " + LOREM + " Annexe sans rapport avec le sujet principal. " * 5
    excerpt = compression.compress_text(text, 25, ["jeton", "rs256"], None)
    assert "RS256" in excerpt
    assert packaging.estimate_tokens(excerpt) <= 25


@pytest.mark.asyncio
async def test_package_markdown_citations_sources_and_warnings() -> None:
    decision = cand(CandidateType.memory, title="SSO via OIDC", text="Décision : SSO via OIDC.")
    chunk = cand(
        title="Audit Atlas",
        text="Contact : [EMAIL]. " + LOREM,
        classification=2,
        pii_redacted=True,
        date=datetime(2026, 9, 12, tzinfo=UTC),
    )
    turn = cand(
        CandidateType.session, title="Session s1 · tour 1", text="Peux-tu résumer ?", extra={"role": "user"}
    )
    decisions = _included(turn, chunk, decision)
    await compression.compress(decisions, query_terms=["authentification", "atlas"], query_vector=None)
    packaged = packaging.render("Préparer la spec Atlas", Intent.specification, decisions)
    md = packaged.markdown
    assert [d.citation for d in packaged.ordered] == ["S1", "S2", "S3"]
    assert packaged.ordered[0].candidate is decision  # decisions section first
    assert (
        md.index("## Décisions en vigueur")
        < md.index("## Extraits de sources")
        < md.index("## Session en cours")
    )
    assert "## Besoins utilisateurs" not in md  # empty sections are omitted
    for line in md.splitlines():
        if line.startswith("- ") and "## Sources" not in line:
            assert line.rstrip().endswith("]")
    assert "[S2] Audit Atlas — Document · v2 · 12/09/2026 · https://wiki.example/atlas" in md
    assert "[EMAIL]" in md  # served from text_redacted
    assert any("C2" in w for w in packaged.warnings)
    assert packaged.tokens_used == packaging.estimate_tokens(md)


def test_citation_markers_cannot_be_forged() -> None:
    c = cand(title="Titre [S9] piégé")
    assert "[S9]" not in packaging.source_line(c, "S1")


def test_empty_package() -> None:
    packaged = packaging.render("Tâche", Intent.general, [])
    assert packaging.EMPTY_CONTEXT in packaged.markdown
    assert "## Sources" not in packaged.markdown


# --- Non-leak presentation ---------------------------------------------------------------------------------


def _excluded(c: Candidate, code: ReasonCode, detail: str, redact: bool = True) -> Decision:
    return Decision(candidate=c, verdict=Verdict(code, detail, redact=redact))


def test_acl_exclusion_redacted_for_viewer_detailed_for_owner() -> None:
    board = cand(title="Note de direction", acl_principals=["role:owner"])
    decision = _excluded(board, ReasonCode.EXCLUDED_ACL, "réservé à : propriétaires")

    hidden = persistence.excluded_from_decision(viewer(), decision)
    assert hidden.redacted is True
    assert hidden.id is None and hidden.title is None and hidden.excerpt is None
    assert hidden.reason_detail != "réservé à : propriétaires"

    owner = viewer(
        principals=frozenset({"project:*", "role:owner", "role:editor", "role:viewer"}),
        sees_restricted_details=True,
    )
    shown = persistence.excluded_from_decision(owner, decision)
    assert shown.redacted is False and shown.title == "Note de direction" and shown.excerpt

    # An owner without the clearance sees the title only (partial), never the content.
    secret = cand(title="Audit C3", classification=3)
    partial_owner = viewer(sees_restricted_details=True, clearance=3, principals=frozenset({"project:*"}))
    acl_secret = cand(title="Audit C3", classification=3, acl_principals=["role:owner"])
    partial = persistence.excluded_from_decision(
        partial_owner, _excluded(acl_secret, ReasonCode.EXCLUDED_ACL, "réservé à : propriétaires")
    )
    assert partial.title == "Audit C3" and partial.excerpt is None
    cls = persistence.excluded_from_decision(
        viewer(), _excluded(secret, ReasonCode.EXCLUDED_CLASSIFICATION, "C3 > habilitation C1")
    )
    assert cls.redacted and cls.title is None and cls.reason_detail == "C3 > habilitation C1"
    admin = persistence.excluded_from_decision(
        viewer(is_admin=True), _excluded(secret, ReasonCode.EXCLUDED_CLASSIFICATION, "x")
    )
    assert admin.title == "Audit C3"


def test_personal_memory_never_described_to_others() -> None:
    personal = cand(
        CandidateType.memory,
        title="Préférence de Bob",
        memory_scope=MemoryScope.user,
        memory_kind=MemoryKind.preference,
        subject_user_id=BOB,
        acl_principals=[f"user:{BOB}"],
    )
    decision = _excluded(personal, ReasonCode.EXCLUDED_SCOPE, "mémoire utilisateur d'un autre utilisateur")
    owner = viewer(sees_restricted_details=True, principals=frozenset({"project:*", "role:owner"}))
    for v in (viewer(), owner):
        item = persistence.excluded_from_decision(v, decision)
        assert item.redacted and item.title is None
    bob = viewer(user_id=BOB, principals=frozenset({"project:*", f"user:{BOB}"}))
    assert persistence.excluded_from_decision(bob, decision).title == "Préférence de Bob"


def test_forgotten_exclusion_hides_the_content() -> None:
    gone = cand(status="forgotten", title="Export")
    item = persistence.excluded_from_decision(
        viewer(), _excluded(gone, ReasonCode.EXCLUDED_FORGOTTEN, "oublié", False)
    )
    assert item.excerpt == FORGOTTEN_TEXT


def test_redact_markdown_replaces_bullet_and_source_line() -> None:
    md = "## Extraits de sources\n\n- **Secret** — contenu [S1]\n- **Public** — ok [S2]\n\n## Sources\n\n[S1] Secret — Document\n[S2] Public — Document"
    out = redact_markdown(md, {"S1": RESTRICTED_TITLE})
    assert "Secret" not in out and "contenu" not in out
    assert f"- {RESTRICTED_TITLE} [S1]" in out and "[S2] Public" in out


def test_exclusion_summary_counts() -> None:
    decisions = [
        _excluded(cand(), ReasonCode.EXCLUDED_ACL, "x"),
        _excluded(cand(), ReasonCode.EXCLUDED_ACL, "x"),
        _excluded(cand(), ReasonCode.EXCLUDED_STALE, "x", False),
    ]
    assert persistence.exclusion_summary(decisions) == {
        ReasonCode.EXCLUDED_ACL: 2,
        ReasonCode.EXCLUDED_STALE: 1,
    }


# --- Pipeline (govern → select → compress → package) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_every_candidate_gets_exactly_one_decision() -> None:
    ctx = GovernanceContext(
        project_id=uuid.uuid4(),
        principals={"project:*", "role:viewer", f"user:{ME}"},
        clearance=1,
        requester_user_id=ME,
        session_id=None,
        scopes=set(MemoryScope),
        source_kinds=None,
        freshness_days={"document": 365, "ticket": 90},
        freshness_override_days=None,
        min_relevance=0.35,
        now=NOW,
    )
    candidates = [
        cand(CandidateType.memory, title="SSO via OIDC", text="Décision : SSO via OIDC pour Atlas."),
        cand(text="Extrait public de la spécification Atlas et de ses jetons."),
        cand(title="Secret", classification=3),
        cand(title="Réservé", acl_principals=["role:owner"]),
        cand(title="Ticket", source_kind=SourceKind.ticket, date=NOW - timedelta(days=200)),
        cand(title="Faible", text="Texte peu pertinent sur la cantine.", score=0.1),
        cand(
            title="Pinned",
            text="Élément épinglé du snapshot.",
            score=0.05,
            pinned=True,
            pinned_label="spec-atlas@v1",
        ),
    ]
    eligible, excluded = [], []
    for c in candidates:
        verdict = evaluate(c, ctx)
        if verdict is None:
            eligible.append(c)
        else:
            excluded.append(Decision(candidate=c, verdict=verdict))
    selected = selection.select_candidates(eligible, token_budget=2000, now=NOW)
    await compression.compress(selected.included, query_terms=["atlas"], query_vector=None)
    packaged = packaging.render("Spec Atlas", Intent.specification, selected.included)
    excluded += selected.excluded
    assert len(packaged.ordered) + len(excluded) == len(candidates)
    codes = {d.verdict.reason_code for d in excluded}
    assert codes == {
        ReasonCode.EXCLUDED_CLASSIFICATION,
        ReasonCode.EXCLUDED_ACL,
        ReasonCode.EXCLUDED_STALE,
        ReasonCode.EXCLUDED_LOW_SCORE,
    }
    pinned = next(d for d in packaged.ordered if d.candidate.pinned)
    assert pinned.verdict.reason_code == ReasonCode.INCLUDED_PINNED
    assert pinned.verdict.reason_detail == "snapshot spec-atlas@v1"
    assert packaged.tokens_used <= 2000


# --- Snapshots ---------------------------------------------------------------------------------------------


def _snapshot(version: int, keys: list[str]) -> ContextSnapshot:
    items = [
        {
            "key": key,
            "citation": f"S{i}",
            "candidate_type": key.split(":")[0],
            "id": str(uuid.uuid4()),
            "title": key,
            "excerpt": "…",
            "forgotten": False,
        }
        for i, key in enumerate(keys, start=1)
    ]
    return ContextSnapshot(name="spec-atlas", version=version, items=items)


def test_snapshot_diff_by_key() -> None:
    old = _snapshot(1, ["memory:a", "chunk:b", "chunk:c"])
    new = _snapshot(2, ["memory:a", "chunk:c", "chunk:d"])
    diff = snapshot_service.diff(old, new)
    assert diff.from_ == 1 and diff.to == 2
    assert [i.key for i in diff.added] == ["chunk:d"]
    assert [i.key for i in diff.removed] == ["chunk:b"]
    assert [i.key for i in diff.unchanged] == ["memory:a", "chunk:c"]
    assert isinstance(diff.added[0], SnapshotItem)


def test_snapshot_names_versions_keys_and_hash() -> None:
    assert snapshot_service.normalize_name("  Spec-Atlas ") == "spec-atlas"
    for bad in ("", "Spec Atlas !", "a" * 200):
        with pytest.raises(ApiError):
            snapshot_service.normalize_name(bad)
    assert snapshot_service.parse_version("latest") == "latest"
    assert snapshot_service.parse_version("v3") == 3
    assert snapshot_service.parse_version(2) == 2
    with pytest.raises(ApiError):
        snapshot_service.parse_version("0")
    lineage = str(uuid.uuid4())
    assert snapshot_service.item_key("memory", "x", lineage) == f"memory:{lineage}"
    assert snapshot_service.item_key("chunk", "abc") == "chunk:abc"
    digest = snapshot_service.content_hash("contenu")
    assert len(digest) == 64 and digest == snapshot_service.content_hash("contenu")


def test_scores_round_trip() -> None:
    c = cand()
    c.scores.bm25, c.scores.rrf, c.scores.final = 12.3456, 0.016393, 0.81234
    scores = persistence.scores_of(Decision(candidate=c, verdict=included_verdict(c, NOW)))
    assert isinstance(scores, Scores)
    assert scores.final == pytest.approx(0.8123, abs=1e-3)


def test_duplicates_jaccard_despite_embeddings_and_original_kept() -> None:
    # Same passage forwarded by e-mail: embeddings differ (title) but the text is identical.
    original = cand(title="Synthèse des entretiens", embedding=[1.0, 0.0], date=NOW - timedelta(days=42))
    forward = cand(title="TR: synthèse entretiens", embedding=[0.8, 0.6], date=NOW - timedelta(days=40))
    # The forward ranks first, yet the earlier original is the one kept.
    assert selection.find_duplicates([forward, original]) == {forward.key: original}
    # Similar but not identical texts: the higher-ranked one stays, whatever the dates.
    edited = cand(text=LOREM.replace("trente", "quarante"), embedding=[1.0, 0.0], date=NOW)
    older = cand(embedding=[1.0, 0.0], date=NOW - timedelta(days=90))
    assert selection.find_duplicates([edited, older]) == {older.key: edited}
