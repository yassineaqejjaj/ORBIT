"""Unit tests of the ingestion building blocks (no infrastructure needed)."""

from __future__ import annotations

import io
import itertools
import json
import math

import pytest

from app.enums import PiiType, SourceKind
from app.ingestion import classifier
from app.ingestion.chunker import chunk_text
from app.ingestion.extractors import (
    CSV,
    DOCX,
    HTML,
    JSON,
    MARKDOWN,
    PDF,
    ExtractionError,
    detect_mime_type,
    extract,
    is_supported,
)
from app.ingestion.importers import RecordParseError, map_records, parse_records
from app.ingestion.normalize import normalize_text
from app.ingestion.pii import analyze, card_is_valid, iban_is_valid, nir_is_valid
from app.ingestion.service import DocumentViewer, title_from_filename
from app.search.embeddings import HashEmbedder, cosine
from app.search.hybrid import reciprocal_rank_fusion
from app.search.opensearch import OSHit, normalize_filters

# --- helpers ---------------------------------------------------------------------------------------------


def _nir(base13: str) -> str:
    key = 97 - (int(base13) % 97)
    return f"{base13}{key:02d}"


def _minimal_pdf(lines: list[str]) -> bytes:
    """A valid one-page PDF with a Helvetica text layer (offsets of the xref computed exactly)."""
    stream_ops = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_ops.append(f"({safe}) Tj T*")
    stream_ops.append("ET")
    stream = "\n".join(stream_ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


# --- normalize --------------------------------------------------------------------------------------------


def test_normalize_nfc_whitespace_and_hyphenation() -> None:
    decomposed = "Café   crème brûlée"
    text = normalize_text(f"{decomposed}\n\n\n\nLa docu-\nmentation   est prête.")
    assert "Café crème" in text
    assert "documentation est prête." in text
    assert "\n\n\n" not in text


# --- PII -----------------------------------------------------------------------------------------------


def test_iban_mod97() -> None:
    assert iban_is_valid("FR14 2004 1010 0505 0001 3M02 606")
    assert iban_is_valid("FR7630006000011234567890189")
    assert not iban_is_valid("FR14 2004 1010 0505 0001 3M02 607")


def test_card_luhn() -> None:
    assert card_is_valid("4111 1111 1111 1111")
    assert card_is_valid("5555555555554444")
    assert not card_is_valid("4111 1111 1111 1112")


def test_nir_key() -> None:
    valid = _nir("2840575123456")
    assert nir_is_valid(valid)
    wrong_key = valid[:-2] + f"{(int(valid[-2:]) % 97) + 1:02d}"
    assert not nir_is_valid(wrong_key)


def test_pii_detection_offsets_and_redaction() -> None:
    nir = _nir("1850775123456")
    text = (
        "Contact : Mme Claire Dubois, claire.dubois@exemple.fr, tél. 06 12 34 56 78 ou +33 1 42 68 53 00.\n"
        f"IBAN FR14 2004 1010 0505 0001 3M02 606, carte 4111 1111 1111 1111, NIR {nir}, poste 192.168.10.24.\n"
        "Faux IBAN FR14 2004 1010 0505 0001 3M02 607 et fausse carte 4111 1111 1111 1112."
    )
    result = analyze(text)
    types = [e.type for e in result.entities]
    for expected in (
        PiiType.EMAIL,
        PiiType.PHONE,
        PiiType.IBAN,
        PiiType.CARD,
        PiiType.NIR,
        PiiType.IP,
        PiiType.PERSON,
    ):
        assert expected in types, f"{expected} non détecté"
    assert types.count(PiiType.IBAN) == 1
    assert types.count(PiiType.CARD) == 1
    for entity in result.entities:
        assert text[entity.start : entity.end] == entity.text
    for placeholder in ("[EMAIL]", "[TÉLÉPHONE]", "[IBAN]", "[CARTE]", "[NIR]", "[IP]", "[PERSONNE]"):
        assert placeholder in result.redacted
    assert "claire.dubois@exemple.fr" not in result.redacted
    assert "4111 1111 1111 1111" not in result.redacted
    assert "4111 1111 1111 1112" in result.redacted  # invalid Luhn: not a card


# --- classifier ----------------------------------------------------------------------------------------


async def test_classifier_rules() -> None:
    plain = await classifier.classify("Planning du sprint et rétrospective.", source_default=1, use_llm=False)
    assert plain.level == 1

    confidential = await classifier.classify(
        "Document confidentiel : grille des salaires 2026.", source_default=1, use_llm=False
    )
    assert confidential.level >= 2
    assert confidential.reasons

    declared = await classifier.classify("Note publique.", source_default=0, declared=3, use_llm=False)
    assert declared.level == 3

    pii = analyze("Virement sur FR14 2004 1010 0505 0001 3M02 606 demain.")
    sensitive = await classifier.classify(
        "Virement demain.", source_default=0, pii_entities=pii.entities, use_llm=False
    )
    assert sensitive.level >= 2


# --- chunker -------------------------------------------------------------------------------------------


def test_chunker_structure_offsets_and_overlap() -> None:
    sentences = " ".join(
        f"La phrase numéro {i} décrit une exigence fonctionnelle du portail client." for i in range(60)
    )
    text = f"# Cahier des charges\n\n## Contexte\n\n{sentences}\n\n## Contraintes\n\nLe portail doit être accessible RGAA."
    chunks = chunk_text(text, target_tokens=120, overlap_tokens=30)
    assert len(chunks) >= 3
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.token_count > 0
    assert any(c.section and "Contexte" in c.section for c in chunks)
    last = chunks[-1]
    assert last.section and "Contraintes" in last.section
    # Consecutive chunks of the same section overlap.
    same_section = [(a, b) for a, b in itertools.pairwise(chunks) if a.section == b.section]
    assert any(b.char_start < a.char_end for a, b in same_section)
    # Chunks of the long section end on a sentence boundary.
    for chunk in chunks[:-1]:
        if chunk.section and "Contexte" in chunk.section:
            assert chunk.text.rstrip().endswith((".", "!", "?"))


def test_chunker_empty() -> None:
    assert chunk_text("   \n ") == []


# --- extractors ----------------------------------------------------------------------------------------


def test_detect_mime_types() -> None:
    assert detect_mime_type("cr.pdf") == PDF
    assert detect_mime_type("spec.docx") == DOCX
    assert detect_mime_type("notes.md") == MARKDOWN
    assert detect_mime_type("page.html") == HTML
    assert detect_mime_type("tickets.json") == JSON
    assert detect_mime_type("crm.csv", "application/vnd.ms-excel") == CSV
    assert not is_supported(detect_mime_type("image.png", "image/png"))


def test_extract_markdown_and_html() -> None:
    md = extract(b"# Titre\n\nUn paragraphe  avec   espaces.", MARKDOWN, "a.md")
    assert md.text.startswith("# Titre")
    assert "Un paragraphe avec espaces." in md.text

    html = extract(
        b"<html><head><title>Portail</title><script>alert(1)</script></head><body>"
        b"<nav>Menu Accueil</nav><h1>Architecture</h1><p>Le portail utilise <b>Keycloak</b>.</p>"
        b"<h2>D\xc3\xa9ploiement</h2><p>Kubernetes.</p></body></html>",
        HTML,
        "page.html",
    )
    assert "# Architecture" in html.text
    assert "## Déploiement" in html.text
    assert "Keycloak" in html.text
    assert "alert(1)" not in html.text
    assert "Menu Accueil" not in html.text


def test_extract_docx_headings() -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Compte rendu COPIL", level=1)
    document.add_paragraph("Décision : le lot 2 démarre en mars.")
    document.add_heading("Risques", level=2)
    document.add_paragraph("Risque : retard du fournisseur.")
    buffer = io.BytesIO()
    document.save(buffer)
    result = extract(buffer.getvalue(), DOCX, "cr.docx")
    assert "# Compte rendu COPIL" in result.text
    assert "## Risques" in result.text
    assert "Décision : le lot 2 démarre en mars." in result.text


def test_extract_pdf() -> None:
    result = extract(
        _minimal_pdf(["Compte rendu du comite", "Decision : lancement du lot 2."]), PDF, "cr.pdf"
    )
    assert "Compte rendu du comite" in result.text
    assert "lancement du lot 2" in result.text
    assert result.metadata.get("page_count") == 1


def test_extract_invalid_pdf() -> None:
    with pytest.raises(ExtractionError):
        extract(b"%PDF-1.4 not really a pdf", PDF, "broken.pdf")


def test_extract_json_records() -> None:
    data = json.dumps([{"title": "Bug connexion", "body": "Impossible de se connecter"}]).encode()
    result = extract(data, JSON, "tickets.json")
    assert "Bug connexion" in result.text


# --- importers ------------------------------------------------------------------------------------------


def test_import_json_column_mapping() -> None:
    raw = json.dumps(
        [
            {
                "id": "SUP-101",
                "subject": "Export PDF en échec",
                "description": "L'export des factures échoue depuis la 2.3.",
                "reporter": "Julie Martin",
                "updated_at": "2026-09-01T10:00:00Z",
                "status": "ouvert",
                "priority": "haute",
                "labels": "export, facturation",
                "classification": "C2",
                "url": "https://support.exemple.fr/SUP-101",
                "customer": "ACME",
            },
            {"notes": ""},
        ]
    ).encode()
    records = map_records(parse_records(raw, "tickets.json", "application/json"), SourceKind.ticket)
    assert len(records) == 1
    record = records[0]
    assert record.external_id == "SUP-101"
    assert "Export PDF en échec" in record.title
    assert record.author == "Julie Martin"
    assert record.classification == 2
    assert record.uri == "https://support.exemple.fr/SUP-101"
    assert set(record.tags) >= {"export", "facturation"}
    assert record.source_updated_at is not None and record.source_updated_at.year == 2026
    assert record.metadata.get("customer") == "ACME"
    assert "L'export des factures échoue" in record.content


def test_import_csv_rows() -> None:
    raw = "external_id;name;notes;owner\nCRM-1;ACME;Client stratégique, renouvellement en octobre;Paul\n".encode()
    records = map_records(parse_records(raw, "crm.csv", "text/csv"), SourceKind.crm)
    assert len(records) == 1
    assert records[0].external_id == "CRM-1"
    assert records[0].title == "ACME"
    assert "renouvellement" in records[0].content


def test_import_rejects_garbage() -> None:
    with pytest.raises(RecordParseError):
        map_records(parse_records(b"{not json", "x.json", "application/json"), SourceKind.ticket)


# --- embeddings / fusion ----------------------------------------------------------------------------------


async def test_hash_embedder_is_deterministic_and_lexical() -> None:
    embedder = HashEmbedder(384)
    a, b, c = await embedder.embed_documents(
        [
            "Le portail client utilise Keycloak pour l'authentification",
            "Authentification du portail client via Keycloak",
            "Recette culinaire de la tarte aux pommes",
        ]
    )
    assert len(a) == 384
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-5)
    assert (
        a
        == (await embedder.embed_documents(["Le portail client utilise Keycloak pour l'authentification"]))[0]
    )
    assert cosine(a, b) > cosine(a, c)
    accents = await embedder.embed_query("délai de réponse")
    plain = await embedder.embed_query("delai de reponse")
    assert cosine(accents, plain) > 0.99


def test_rrf_fusion_orders_by_combined_rank() -> None:
    bm25 = [OSHit(id="a", score=9.0, source={}), OSHit(id="b", score=5.0, source={})]
    dense = [OSHit(id="b", score=0.9, source={}), OSHit(id="c", score=0.8, source={})]
    fused = reciprocal_rank_fusion(bm25, dense, k=60)
    assert fused[0].id == "b"
    assert {h.id for h in fused} == {"a", "b", "c"}
    top = fused[0]
    assert top.bm25_rank == 2 and top.dense_rank == 1
    assert math.isclose(top.rrf, 1 / 62 + 1 / 61)
    assert top.rrf_norm == pytest.approx(1.0)
    assert all(0.0 <= h.rrf_norm <= 1.0 for h in fused)


def test_normalize_filters() -> None:
    clauses = normalize_filters(
        {"status": "active", "tags": ["a", "b"], "classification": {"lte": 2}, "x": None}
    )
    assert {"term": {"status": "active"}} in clauses
    assert {"terms": {"tags": ["a", "b"]}} in clauses
    assert {"range": {"classification": {"lte": 2}}} in clauses
    assert len(clauses) == 3


# --- service helpers --------------------------------------------------------------------------------------


def test_title_from_filename() -> None:
    assert title_from_filename("compte_rendu COPIL.v2.pdf") == "compte rendu COPIL.v2"
    assert title_from_filename(None) == "Document sans titre"


def test_document_viewer_rules() -> None:
    import uuid

    viewer = DocumentViewer(
        project_id=uuid.uuid4(),
        principals=frozenset({"project:*", "role:viewer"}),
        clearance=1,
        is_admin=False,
        can_see_pii=False,
    )
    assert viewer.allows(["project:*"], 1)
    assert not viewer.allows(["project:*"], 2)
    assert not viewer.allows(["role:editor"], 0)
    assert not viewer.allows([], 0)
    filters = viewer.search_filters()
    assert {"term": {"status": "active"}} in filters
    assert {"range": {"classification": {"lte": 1}}} in filters
