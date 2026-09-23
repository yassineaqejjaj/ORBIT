"""Platform metadata (public)."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.enums import REASON_CODE_LABELS
from app.llm import client as llm_client
from app.schemas import Meta

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=Meta, summary="Version, modèles et libellés des codes de raison")
async def get_meta() -> Meta:
    return Meta(
        version=settings.app_version,
        embedding_model=settings.embedding_model,
        reranker=settings.reranker,
        llm=llm_client.model_label(),
        reason_codes={code.value: label for code, label in REASON_CODE_LABELS.items()},
    )
