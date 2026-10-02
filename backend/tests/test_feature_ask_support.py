"""Shared seed for the F4 tests (« Demander à ORBIT », Teams). Fictitious data only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ActorType, DocumentStatus, MemoryKind, MemoryScope, MemoryStatus, SourceKind
from app.models import Chunk, Document, MemoryItem, Source
from tests.conftest import UserInfo

NOW = datetime.now(UTC)
PUBLIC_TEXT = (
    "Atlas sera livré sous forme de PWA pour couvrir mobile et ordinateur avec une seule base de code. "
    "La PWA fonctionne hors ligne grâce au service worker."
)
SECRET_TEXT = "Audit : la PWA Atlas expose une faille XSS critique sur le service worker."
PRIVATE_TEXT = "Bob pense que la PWA Atlas est trop lente sur son vieux téléphone."


async def add_member(admin: httpx.AsyncClient, slug: str, user: UserInfo, role: str = "viewer") -> None:
    response = await admin.post(f"/api/v1/projects/{slug}/members", json={"email": user.email, "role": role})
    assert response.status_code in (200, 201), response.text


async def seed_atlas(
    session: AsyncSession, project: dict[str, Any], bob_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    project_id = uuid.UUID(str(project["id"]))
    source = Source(project_id=project_id, name="Wiki Atlas", kind=SourceKind.document)
    session.add(source)
    await session.flush()
    ids: dict[str, uuid.UUID] = {}
    for key, title, text, level in (
        ("public", "Cadrage Atlas", PUBLIC_TEXT, 1),
        ("secret", "Audit de sécurité Atlas", SECRET_TEXT, 3),
    ):
        document = Document(
            project_id=project_id,
            source_id=source.id,
            title=title,
            uri=f"https://wiki.example/{uuid.uuid4().hex[:6]}",
            status=DocumentStatus.indexed,
            classification=level,
            source_updated_at=NOW - timedelta(days=3),
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                project_id=project_id,
                document_id=document.id,
                version=document.current_version,
                ordinal=0,
                text=text,
                text_redacted=text,
                token_count=len(text.split()),
                classification=level,
                acl_principals=list(document.acl_principals),
            )
        )
        ids[key] = document.id

    def memory(title: str, content: str, **kwargs: Any) -> MemoryItem:
        item = MemoryItem(
            project_id=project_id,
            lineage_id=uuid.uuid4(),
            scope=kwargs.pop("scope", MemoryScope.project),
            kind=kwargs.pop("kind", MemoryKind.decision),
            status=MemoryStatus.validated,
            title=title,
            content=content,
            confidence=0.9,
            classification=kwargs.pop("classification", 1),
            valid_from=NOW - timedelta(days=5),
            created_by_type=ActorType.system,
            **kwargs,
        )
        session.add(item)
        return item

    decision = memory(
        "Choix d'une PWA pour Atlas",
        "Décision : Atlas est développé en PWA plutôt qu'en application native, pour réduire les coûts de maintenance.",
        rationale="Une seule base de code",
    )
    auth = memory(
        "Authentification Atlas via OIDC",
        "Décision : l'authentification Atlas passe par OIDC avec le fournisseur d'identité interne.",
    )
    private = memory(
        "Avis de Bob sur la PWA Atlas",
        PRIVATE_TEXT,
        scope=MemoryScope.user,
        kind=MemoryKind.preference,
        subject_user_id=bob_id,
        acl_principals=[f"user:{bob_id}"],
    )
    await session.commit()
    ids.update(decision=decision.id, auth=auth.id, private=private.id)
    return ids
