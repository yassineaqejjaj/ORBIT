"""Connector secrets: Fernet encryption (``ORBIT_ENCRYPTION_KEY``) and masked hints (docs/FEATURES.md F5)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.errors import ApiError

ENCRYPTION_MISSING = (
    "Le chiffrement des secrets n'est pas configuré : définissez ORBIT_ENCRYPTION_KEY "
    "(clé Fernet) pour utiliser les connecteurs"
)


def _fernet() -> Fernet:
    key = (settings.encryption_key or "").strip()
    if not key:
        raise ApiError(503, ENCRYPTION_MISSING, code="encryption_key_missing")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise ApiError(
            503, "ORBIT_ENCRYPTION_KEY n'est pas une clé Fernet valide", code="encryption_key_invalid"
        ) from exc


def require_encryption() -> None:
    """503 ``encryption_key_missing`` when no usable key is configured."""
    _fernet()


def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ApiError(
            503,
            "Secret du connecteur illisible (clé de chiffrement modifiée ?) : ressaisissez-le",
            code="secret_unreadable",
        ) from exc


def hint(secret: str) -> str:
    """Masked hint shown instead of the secret (last 4 characters only)."""
    secret = secret.strip()
    if len(secret) <= 8:
        return "••••"
    return f"••••{secret[-4:]}"
