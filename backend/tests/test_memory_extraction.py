"""Rule-based French extraction (ARCHITECTURE §7 step 7) on DEMO.md-style texts, and conflict markers."""

from __future__ import annotations

from types import SimpleNamespace

from app.enums import MemoryKind, SourceKind, TurnRole
from app.memory.conflicts import divergences, numeric_divergence, replacement_phrase, topic_similarity
from app.memory.consolidation import summarize_turns
from app.memory.extractor import extract_statements, is_meeting_record, make_title
from app.memory.short_term import Turn

CR_COPIL = """Compte rendu — Comité de pilotage Atlas

Participants : Claire Martin, Hugo Bernard, Sofia Leroy.

Décision : l'authentification se fera en SSO OIDC (Keycloak), abandon du login email/mot de passe.
Décision : pilote le 15 novembre sur le site de Lyon.
Contrainte : conformité RGAA AA obligatoire pour toutes les interfaces.
Risque : adoption faible si la réservation prend plus de 30 s.
"""

BESOINS = """Synthèse des retours utilisateurs

Besoin : pouvoir réserver un poste en moins de 30 secondes depuis son téléphone.
En tant que collaborateur, je veux voir les postes libres à proximité de mon équipe.
Les utilisateurs souhaitent recevoir un rappel la veille de leur réservation.
"""

INVENTAIRE = "Inventaire immobilier Lyon. Le site de Lyon compte 720 postes répartis sur 4 étages."


def _kinds(text: str, **kwargs: object) -> dict[MemoryKind, list[str]]:
    result: dict[MemoryKind, list[str]] = {}
    for statement in extract_statements(text, **kwargs):  # type: ignore[arg-type]
        result.setdefault(statement.kind, []).append(statement.content)
    return result


def test_meeting_record_decisions_constraints_risks() -> None:
    statements = extract_statements(CR_COPIL, source_kind=SourceKind.note)
    kinds = {s.kind for s in statements}
    assert {MemoryKind.decision, MemoryKind.constraint, MemoryKind.risk} <= kinds
    decisions = [s for s in statements if s.kind == MemoryKind.decision]
    assert len(decisions) == 2
    assert all(s.explicit_decision for s in decisions)
    assert any("Keycloak" in s.content for s in decisions)
    assert any("15 novembre" in s.content for s in decisions)
    # Participants lists are not memory.
    assert not any("Participants" in s.content for s in statements)
    for statement in statements:
        assert statement.title
        assert len(statement.title) <= 90
        assert statement.title[0].isupper()
        assert 0 < statement.confidence <= 1


def test_requirements_patterns() -> None:
    requirements = _kinds(BESOINS, source_kind=SourceKind.feedback).get(MemoryKind.requirement, [])
    assert len(requirements) == 3
    assert any("30 secondes" in text for text in requirements)
    assert any("En tant que collaborateur" in text for text in requirements)
    assert any("rappel" in text for text in requirements)


def test_inventory_fact() -> None:
    facts = _kinds(INVENTAIRE, source_kind=SourceKind.document).get(MemoryKind.fact, [])
    assert any("720 postes" in text for text in facts)


def test_meeting_record_detection() -> None:
    cr = SimpleNamespace(title="CR atelier cadrage")
    spec = SimpleNamespace(title="Spécification fonctionnelle Atlas")
    assert is_meeting_record(cr)  # type: ignore[arg-type]
    assert is_meeting_record(spec, "Compte rendu de la réunion du 3 mars")  # type: ignore[arg-type]
    assert not is_meeting_record(spec, "Objectifs du produit")  # type: ignore[arg-type]


def test_make_title_is_short_and_capitalized() -> None:
    title = make_title(
        "l'application sera une PWA plutôt qu'une application native, afin de limiter les coûts de "
        "maintenance et de publier les mises à jour sans passer par les magasins d'applications"
    )
    assert len(title) <= 90
    assert title[0].isupper()


def test_numeric_contradiction_markers() -> None:
    a = "Le site de Lyon compte 720 postes."
    b = "Après réaménagement, le site de Lyon compte 650 postes."
    assert numeric_divergence(a, b)
    assert divergences(a, b)
    assert topic_similarity(a, b) > 0.5
    assert not numeric_divergence(a, "Le site de Lyon compte 720 postes de travail.")


def test_explicit_replacement_phrase() -> None:
    old = "Décision : application mobile native iOS/Android."
    new = "Décision : l'application sera une PWA plutôt qu'une application native."
    assert replacement_phrase(new, old)
    assert replacement_phrase(old, new) is None


def test_extractive_session_summary() -> None:
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    turns = [
        Turn(TurnRole.user, "Prépare la user story de réservation par QR code.", start),
        Turn(TurnRole.agent, "Bonjour ! Je regarde le dossier.", start + timedelta(minutes=1)),
        Turn(
            TurnRole.agent,
            "La décision retenue est le check-in par QR code sur le poste. Le pilote doit démarrer à Lyon.",
            start + timedelta(minutes=2),
        ),
        Turn(TurnRole.tool, "ok", start + timedelta(minutes=3)),
    ]
    lines = summarize_turns(turns)
    assert lines[0].startswith("Utilisateur : Prépare la user story")
    assert any("check-in par QR code" in line for line in lines)
    assert all(len(line) < 400 for line in lines)
    assert summarize_turns([]) == []
