"""Documents (STUB — implemented by the ingestion teammate).

Endpoints (docs/API.md « Sources & documents »). Upload/text/import accept agent keys. Every read is
filtered by the caller's ACL principals and clearance (``app.governance.acl``); an inaccessible
document is a 404. ``PiiEntity.text`` is omitted for callers below ``editor``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response

from app.deps import AgentEditorAccess, EditorAccess, OwnerAccess, SessionDep, ViewerAccess
from app.enums import DocumentStatus, SourceKind
from app.schemas import (
    DocumentDetail,
    DocumentSummary,
    DocumentUpdateIn,
    ForgetIn,
    ImportResult,
    Job,
    Page,
    PageParams,
    TextDocumentIn,
    page_params,
)

router = APIRouter(prefix="/projects/{slug}/documents", tags=["documents"])


@router.get("", response_model=Page[DocumentSummary], summary="Documents du projet (filtrés par droits)")
async def list_documents(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    source_id: uuid.UUID | None = Query(default=None),
    status_: DocumentStatus | None = Query(default=None, alias="status"),
    source_kind: SourceKind | None = Query(default=None),
    classification: int | None = Query(default=None, ge=0, le=3),
    q: str | None = Query(default=None, max_length=200),
) -> Page[DocumentSummary]:
    raise NotImplementedError


@router.post(
    "/upload",
    response_model=list[DocumentSummary],
    status_code=status.HTTP_201_CREATED,
    summary="Téléverser des fichiers (statut pending)",
)
async def upload_documents(
    access: AgentEditorAccess,
    session: SessionDep,
    files: list[UploadFile] = File(..., description="Fichiers (PDF, DOCX, Markdown, texte, HTML, JSON, CSV)"),
    source_id: uuid.UUID | None = Form(default=None),
    classification: int | None = Form(default=None, ge=0, le=3),
    acl_principals: str | None = Form(default=None, description="CSV, ex. role:editor,user:<uuid>"),
    tags: str | None = Form(default=None, description="CSV"),
) -> list[DocumentSummary]:
    raise NotImplementedError


@router.post(
    "/text", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED, summary="Ingérer un texte"
)
async def create_text_document(
    body: TextDocumentIn, access: AgentEditorAccess, session: SessionDep
) -> DocumentSummary:
    raise NotImplementedError


@router.post(
    "/import",
    response_model=ImportResult,
    summary="Importer des tickets / CRM / retours / traces (JSON ou CSV)",
)
async def import_documents(
    access: AgentEditorAccess,
    session: SessionDep,
    file: UploadFile = File(...),
    source_kind: SourceKind = Form(...),
    source_id: uuid.UUID | None = Form(default=None),
) -> ImportResult:
    raise NotImplementedError


@router.get("/{document_id}", response_model=DocumentDetail, summary="Détail d'un document")
async def get_document(document_id: uuid.UUID, access: ViewerAccess, session: SessionDep) -> DocumentDetail:
    raise NotImplementedError


@router.patch(
    "/{document_id}",
    response_model=DocumentSummary,
    summary="Modifier titre, classification, ACL, étiquettes",
)
async def update_document(
    document_id: uuid.UUID, body: DocumentUpdateIn, access: EditorAccess, session: SessionDep
) -> DocumentSummary:
    raise NotImplementedError


@router.post("/{document_id}/reprocess", response_model=Job, summary="Relancer le traitement")
async def reprocess_document(document_id: uuid.UUID, access: EditorAccess, session: SessionDep) -> Job:
    raise NotImplementedError


@router.post("/{document_id}/forget", response_model=DocumentSummary, summary="Oubli sélectif d'un document")
async def forget_document(
    document_id: uuid.UUID, body: ForgetIn, access: OwnerAccess, session: SessionDep
) -> DocumentSummary:
    raise NotImplementedError


@router.get(
    "/{document_id}/raw",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "Fichier original"}},
    summary="Télécharger le fichier original",
)
async def get_document_raw(document_id: uuid.UUID, access: EditorAccess, session: SessionDep) -> Response:
    raise NotImplementedError
