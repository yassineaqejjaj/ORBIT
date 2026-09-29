"""Demo data set « Atlas » (docs/DEMO.md): manifest ↔ files coherence, parsing, relative dates, coverage."""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime

import pytest

from app.seed import manifest as mf

NOW = datetime(2026, 9, 29, 14, 30, tzinfo=UTC)
FR_PHONE = re.compile(r"\b0[67](?: \d{2}){4}\b")
EMAIL = re.compile(r"\b[\w.]+@nordalis\.example\b")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return mf.load_manifest()


def _doc(manifest: dict, key: str) -> dict:
    return next(d for d in manifest["documents"] if d["key"] == key)


def test_manifest_is_valid(manifest: dict) -> None:
    assert mf.validate_manifest(manifest) == []


def test_every_data_file_is_referenced(manifest: dict) -> None:
    referenced = {d["file"] for d in manifest["documents"]} | {
        d["append"] for d in manifest["documents"] if d.get("append")
    }
    on_disk = {
        str(p.relative_to(mf.DATA_DIR))
        for p in mf.DATA_DIR.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    assert on_disk == referenced


def test_rendering_resolves_every_token(manifest: dict) -> None:
    assert mf.render("{{J-1}}", NOW) == "2026-09-28T09:00:00+00:00"
    assert mf.render("{{date:J-28}}", NOW) == "1er septembre 2026"
    assert mf.render("{{date:J-56}}", NOW) == "4 août 2026"
    # Never in the future, even for J-0 after business hours.
    assert mf.day_at(NOW.replace(hour=8), 0, hour=18) < NOW.replace(hour=8)
    for doc in manifest["documents"]:
        text = mf.document_text(doc, NOW) if doc["mode"] == "text" else mf.import_file(doc, NOW)[1].decode()
        assert "{{" not in text, doc["key"]


def test_imports_parse_with_rendered_dates(manifest: dict) -> None:
    for doc in (d for d in manifest["documents"] if d["mode"] == "import"):
        records = mf.import_records(doc, NOW)
        assert len(records) == doc["records"]
        for record in records:
            value = record.get("updated_at") or record.get("date")
            assert datetime.fromisoformat(value) <= NOW
            content = (
                record.get("description")
                or record.get("body")
                or record.get("content")
                or record.get("notes")
            )
            assert content and len(content.split()) >= 20, record


def test_documents_cover_every_demo_mechanism(manifest: dict) -> None:
    v1, v2 = _doc(manifest, "spec-v1"), _doc(manifest, "spec-v2")
    assert (v1["title"], v1["external_id"], v1["source"]) == (v2["title"], v2["external_id"], v2["source"])
    assert (v1["offset_days"], v2["offset_days"]) == (49, 6)
    v1_text, v2_text = mf.document_text(v1, NOW), mf.document_text(v2, NOW)
    assert "native" in v1_text and "800 postes" in v1_text
    assert "PWA" in v2_text and "650 postes" in v2_text and "QR code" in v2_text

    inventory = mf.document_text(_doc(manifest, "inventaire"), NOW)
    assert "Le site de Lyon compte 720 postes" in inventory

    kickoff = mf.document_text(_doc(manifest, "cr-kickoff"), NOW)
    cadrage = mf.document_text(_doc(manifest, "cr-cadrage"), NOW)
    copil = mf.document_text(_doc(manifest, "cr-copil"), NOW)
    sprint = mf.document_text(_doc(manifest, "cr-sprint6"), NOW)
    assert "Décision : l'application Atlas sera une application mobile native" in kickoff
    assert "Décision : l'application Atlas sera une PWA" in cadrage
    assert (
        "SSO OIDC" in copil
        and "15 novembre" in copil
        and "Contrainte :" in copil
        and "RGAA niveau AA" in copil
    )
    assert "Décision : le check-in se fera par QR code" in sprint and "Risque : adoption faible" in sprint

    synthesis = mf.document_text(_doc(manifest, "synthese"), NOW)
    assert "12 entretiens" in synthesis
    assert len(re.findall(r"^- En tant qu", synthesis, re.MULTILINE)) >= 6
    duplicate = mf.document_text(_doc(manifest, "synthese-tr"), NOW)
    assert duplicate.startswith("TR: synthèse entretiens") and synthesis.strip() in duplicate

    budget = _doc(manifest, "budget")
    assert budget["classification"] == 3 and budget["acl"] == ["role:owner"]
    assert _doc(manifest, "benchmark")["offset_days"] == 400
    assert next(s for s in manifest["sources"] if s["key"] == "veille")["kind"] == "url"
    assert _doc(manifest, "teletravail")["offset_days"] == 25
    assert "2 jours par semaine" in mf.document_text(_doc(manifest, "teletravail"), NOW)


def test_business_records(manifest: dict) -> None:
    tickets = mf.import_records(_doc(manifest, "jira"))
    assert [t["id"] for t in tickets] == [f"ATLAS-{n}" for n in range(101, 113)]
    ages = sorted(int(t["updated_at"][4:-2]) for t in tickets)
    assert sum(1 for age in ages if age > 90) == 3 and ages[0] == 2 and ages[-1] == 120

    crm_doc = _doc(manifest, "crm")
    crm = mf.import_records(crm_doc)
    assert len(crm) == 5 and crm_doc["classification"] == 2
    assert next(s for s in manifest["sources"] if s["key"] == "crm")["default_classification"] == 2
    for record in crm:
        assert FR_PHONE.search(record["phone"]) and EMAIL.search(record["email"])
        assert (
            FR_PHONE.search(record["notes"])
            or EMAIL.search(record["notes"])
            or "ne pas diffuser" in record["notes"]
        )
        assert record["classification"] == "Confidentiel"

    feedback = mf.import_records(_doc(manifest, "beta"))
    assert len(feedback) == 8
    assert any("salle 3B" in f["subject"] for f in feedback)
    assert any("faible luminosité" in f["subject"] for f in feedback)
    assert len(mf.import_records(_doc(manifest, "traces"))) == 3


def test_memory_sessions_and_history(manifest: dict) -> None:
    memory = {m["key"]: m for m in manifest["memory"]}
    org = [m for m in memory.values() if m.get("org")]
    assert {m["title"] for m in org} == {
        "Toutes les applications Nordalis respectent le RGAA niveau AA",
        "Hébergement des données personnelles dans l'UE obligatoire",
    }
    assert all(m["kind"] == "constraint" and m["status"] == "validated" for m in org)
    assert memory["pref-camille"]["subject"] == "camille" and memory["pref-leo"]["subject"] == "leo"
    assert memory["fact-prestataire"]["forget"]["reason"].startswith("Information erronée")
    assert memory["short-expired"]["expire"] is True

    sessions = {s["id"]: s for s in manifest["sessions"]}
    assert len(sessions["atlas-spec-redaction"]["turns"]) == 4
    assert sessions["atlas-atelier-maquettes"]["expire"] is True

    requests = manifest["context_requests"]
    assert 28 <= len(requests) <= 35
    assert {r["agent"] for r in requests} == {"produit", "design", "engineering"}
    agents = {a["key"]: a["acts_for"] for a in manifest["agents"]}
    assert all(r["user"] == agents[r["agent"]] for r in requests if r["via"] == "agent")
    assert len({r["day_offset"] for r in requests}) == 14
    saves = [r["save_snapshot"] for r in requests if r.get("save_snapshot")]
    assert saves == ["spec-atlas", "spec-atlas", "design-atlas", "archi-atlas"]
    derived = [r for r in requests if r.get("base_snapshot")]
    assert {r["save_snapshot"] for r in derived} == {"design-atlas", "archi-atlas"}
    assert all(r["base_snapshot"] == {"name": "spec-atlas", "version": 2} for r in derived)
    ratings = [r["feedback"]["rating"] for r in requests if r.get("feedback")]
    assert ratings and min(ratings) >= 3 and max(ratings) <= 5
    assert sum(1 for r in requests if r.get("feedback", {}).get("flag_outdated")) == 1


def test_validation_reports_broken_data(manifest: dict) -> None:
    broken = copy.deepcopy(manifest)
    broken["documents"][0]["file"] = "veille/absent.md"
    broken["documents"][1]["source"] = "inconnue"
    _doc(broken, "spec-v2")["version"] = 3
    broken["context_requests"][0]["base_snapshot"] = {"name": "jamais", "version": 1}
    broken["memory"][0]["scope"] = "project"
    errors = mf.validate_manifest(broken)
    assert any("fichier manquant" in e for e in errors)
    assert any("source « inconnue »" in e for e in errors)
    assert any("version 3 inattendue" in e for e in errors)
    assert any("jamais enregistré" in e for e in errors)
    assert any("organisationnelle" in e for e in errors)


def test_word_counts_are_in_range(manifest: dict) -> None:
    for doc in (d for d in manifest["documents"] if d["mode"] == "text"):
        assert mf.MIN_WORDS <= mf.word_count(mf.raw_document_text(doc)) <= mf.MAX_WORDS, doc["key"]


def test_import_files_are_understood_by_the_real_importer(manifest: dict) -> None:
    from app.ingestion import importers

    for doc in (d for d in manifest["documents"] if d["mode"] == "import"):
        name, content, content_type = mf.import_file(doc, NOW)
        records = importers.map_records(
            importers.parse_records(content, name, content_type), doc["source_kind"]
        )
        assert len(records) == doc["records"], doc["key"]
        for record in records:
            assert record.external_id and record.title and record.source_updated_at is not None
            assert record.source_updated_at <= NOW
        if doc["key"] == "crm":
            assert {r.classification for r in records} == {2}
