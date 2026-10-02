"""Microsoft Teams outgoing webhook → « Demander à ORBIT » (F4, docs/integrations/teams.md).

* Each request is authenticated with ``Authorization: HMAC <base64>``: HMAC-SHA256 of the raw body with
  the base64-decoded security token Teams gave when the webhook was created. The token is stored
  Fernet-encrypted with ``ORBIT_ENCRYPTION_KEY`` (configuration refused without that key).
* Replays are refused: each Teams activity id is accepted once (``ask_messages.external_id``) and
  activities older than :data:`MAX_AGE` are rejected.
* The Teams author (``from.aadObjectId`` or e-mail) is mapped to an ORBIT user who must be a member of
  the project; the question then goes through exactly the same governed path as the web UI.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.deps import Principal, ProjectAccess, get_project_access
from app.errors import ApiError, conflict, not_found, unauthorized, validation_error
from app.features.ask import service as ask_service
from app.features.ask.schemas import AskIn, AskOut
from app.models import Project, User
from app.models.features_ask import AskConversation, AskMessage, Integration
from app.services import projects as project_service

KIND = "teams"
MAX_AGE = timedelta(minutes=15)
CONVERSATION_REUSE = timedelta(minutes=30)
ENCRYPTION_MISSING = (
    "Chiffrement non configuré : définissez ORBIT_ENCRYPTION_KEY (clé Fernet) sur le serveur avant de "
    "connecter Microsoft Teams — le secret du webhook n'est jamais stocké en clair."
)
NOT_LINKED = (
    "Votre compte Teams n'est pas relié à un membre de ce projet ORBIT. "
    "Demandez à un propriétaire du projet de vous ajouter dans « Connecter Microsoft Teams »."
)
_MENTION = re.compile(r"<at>.*?</at>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


# --- Secrets ----------------------------------------------------------------------------------------------


def encryption_available() -> bool:
    if not settings.encryption_key:
        return False
    try:
        Fernet(settings.encryption_key.encode())
    except (ValueError, binascii.Error):
        return False
    return True


def _fernet() -> Fernet:
    if not encryption_available():
        raise conflict(ENCRYPTION_MISSING)
    return Fernet(settings.encryption_key.encode())


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ApiError, ValueError):
        return None


def validate_secret(secret: str) -> bytes:
    """The Teams security token is base64; returns the decoded HMAC key (422 otherwise)."""
    try:
        key = base64.b64decode(secret.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise validation_error(
            "Le jeton de sécurité Teams doit être la valeur base64 fournie par Teams"
        ) from exc
    if len(key) < 16:
        raise validation_error("Jeton de sécurité Teams trop court")
    return key


def sign(body: bytes, secret: str) -> str:
    """``Authorization`` header value Teams computes for ``body`` (used by tests and docs)."""
    digest = hmac.new(base64.b64decode(secret), body, hashlib.sha256).digest()
    return f"HMAC {base64.b64encode(digest).decode()}"


def verify_signature(body: bytes, authorization: str | None, secret: str) -> bool:
    if not authorization or not authorization.startswith("HMAC "):
        return False
    try:
        provided = base64.b64decode(authorization[5:].strip(), validate=True)
        key = base64.b64decode(secret, validate=True)
    except (binascii.Error, ValueError):
        return False
    expected = hmac.new(key, body, hashlib.sha256).digest()
    return hmac.compare_digest(provided, expected)


# --- Configuration ----------------------------------------------------------------------------------------


async def get_integration(session: AsyncSession, project_id: uuid.UUID) -> Integration | None:
    return await session.scalar(
        select(Integration).where(Integration.project_id == project_id, Integration.kind == KIND)
    )


def mapping_of(integration: Integration | None) -> dict[str, str]:
    if integration is None:
        return {}
    raw = (integration.config or {}).get("user_mapping") or {}
    return {str(k): str(v) for k, v in raw.items()}


def normalize_teams_id(value: str) -> str:
    return value.strip().lower()


# --- Incoming activities ----------------------------------------------------------------------------------


def question_of(activity: dict[str, Any]) -> str:
    text = str(activity.get("text") or "")
    text = _MENTION.sub(" ", text)
    text = html.unescape(_TAG.sub(" ", text))
    return " ".join(text.split())


def _activity_time(activity: dict[str, Any]) -> datetime | None:
    raw = activity.get("timestamp") or activity.get("localTimestamp")
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def teams_reply(text: str) -> dict[str, Any]:
    return {"type": "message", "text": text}


async def _resolve_user(
    session: AsyncSession, project: Project, integration: Integration, author: dict[str, Any]
) -> User | None:
    mapping = {normalize_teams_id(k): v for k, v in mapping_of(integration).items()}
    candidates = [
        str(author.get(key) or "") for key in ("aadObjectId", "email", "userPrincipalName") if author.get(key)
    ]
    for candidate in candidates:
        user_id = mapping.get(normalize_teams_id(candidate))
        if user_id:
            try:
                return await session.get(User, uuid.UUID(user_id))
            except ValueError:
                return None
    # Fallback: an e-mail that matches an ORBIT account (membership is checked by the caller).
    for candidate in candidates:
        if "@" in candidate:
            user = await session.scalar(select(User).where(func.lower(User.email) == candidate.lower()))
            if user is not None:
                return user
    return None


async def _recent_conversation(session: AsyncSession, access: ProjectAccess) -> uuid.UUID | None:
    return await session.scalar(
        select(AskConversation.id)
        .where(
            AskConversation.project_id == access.project_id,
            AskConversation.user_id == access.principal.user_id,
            AskConversation.channel == "teams",
            AskConversation.updated_at >= utcnow() - CONVERSATION_REUSE,
        )
        .order_by(AskConversation.updated_at.desc())
        .limit(1)
    )


def format_answer(answer: AskOut, *, app_url: str, slug: str) -> str:
    lines = [answer.answer]
    if answer.citations:
        lines.append("")
        lines.append("**Sources**")
        for item in answer.citations:
            link = ""
            if app_url:
                if item.memory_item_id:
                    link = f"{app_url}/projects/{slug}/memory/{item.memory_item_id}"
                elif item.document_id:
                    link = f"{app_url}/projects/{slug}/documents/{item.document_id}"
            title = f"[{item.title}]({link})" if link else item.title
            lines.append(f"- [{item.citation}] {title}")
    if answer.warnings:
        lines.append("")
        lines.extend(f"_{warning}_" for warning in answer.warnings)
    if app_url:
        lines.append("")
        lines.append(
            f"[Continuer dans ORBIT]({app_url}/projects/{slug}/ask?conversation={answer.conversation_id})"
        )
    return "\n".join(lines)


async def handle_activity(
    session: AsyncSession, slug: str, body: bytes, authorization: str | None
) -> dict[str, Any]:
    project = await project_service.get_by_slug(session, slug)
    integration = await get_integration(session, project.id) if project is not None else None
    if project is None or integration is None or not integration.enabled:
        raise not_found("Intégration Teams introuvable")
    secret = decrypt_secret(integration.secret_encrypted)
    if secret is None or not verify_signature(body, authorization, secret):
        raise unauthorized("Signature HMAC Teams invalide")
    try:
        activity = json.loads(body)
    except ValueError as exc:
        raise validation_error("Message Teams illisible") from exc
    if not isinstance(activity, dict):
        raise validation_error("Message Teams illisible")
    sent_at = _activity_time(activity)
    if sent_at is not None and utcnow() - sent_at > MAX_AGE:
        raise unauthorized("Message Teams expiré")
    activity_id = str(activity.get("id") or "").strip()
    external_id = f"teams:{project.id}:{activity_id}" if activity_id else None
    if external_id and await session.scalar(
        select(AskMessage.id).where(AskMessage.external_id == external_id)
    ):
        raise conflict("Message Teams déjà traité")

    author = activity.get("from") if isinstance(activity.get("from"), dict) else {}
    user = await _resolve_user(session, project, integration, author or {})
    if user is None:
        return teams_reply(NOT_LINKED)
    try:
        access = await get_project_access(session, Principal.for_user(user), slug)
    except ApiError:
        return teams_reply(NOT_LINKED)

    question = question_of(activity)
    if not question:
        return teams_reply(
            "Posez une question après la mention, par exemple : « Pourquoi a-t-on choisi une PWA ? »"
        )
    conversation_id = await _recent_conversation(session, access)
    answer = await ask_service.ask(
        session,
        access,
        AskIn(question=question[:2000], conversation_id=conversation_id),
        channel="teams",
        external_id=external_id,
    )
    app_url = str((integration.config or {}).get("app_url") or "").rstrip("/")
    return teams_reply(format_answer(answer, app_url=app_url, slug=slug))
