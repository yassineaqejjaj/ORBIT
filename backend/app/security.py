"""Credentials: argon2 password hashing, session JWT (HS256) and agent API keys.

Agent keys have the form ``orb_<prefix8>_<secret32>`` (base62). Only ``sha256(key)`` is stored; the
prefix (unique, indexed) is used for the lookup, the hash is compared in constant time.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "orbit"
SESSION_COOKIE_NAME = "orbit_session"
API_KEY_HEADER = "X-Orbit-Key"
API_KEY_SCHEME = "orb"
API_KEY_PREFIX_LENGTH = 8
API_KEY_SECRET_LENGTH = 32

_BASE62 = string.ascii_letters + string.digits
_PREFIX_ALPHABET = string.ascii_lowercase + string.digits

_hasher = PasswordHasher()  # argon2id, library defaults (RFC 9106 low-memory profile)
_DUMMY_HASH = _hasher.hash("orbit-timing-equaliser")


# --- Passwords ------------------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time check. A missing hash still costs one argon2 verification (no user enumeration)."""
    if not password_hash:
        with contextlib.suppress(VerificationError):
            _hasher.verify(_DUMMY_HASH, password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def password_fingerprint(password_hash: str) -> str:
    """Short fingerprint of the password hash, embedded in JWTs: changing a password revokes sessions."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


# --- Session tokens -------------------------------------------------------------------------------


class TokenError(Exception):
    """Raised when a session token is missing, malformed, expired or revoked."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: uuid.UUID
    password_fingerprint: str | None
    issued_at: datetime
    expires_at: datetime
    token_id: str


def create_access_token(
    user_id: uuid.UUID,
    *,
    password_hash: str | None = None,
    ttl_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    ttl = timedelta(minutes=ttl_minutes if ttl_minutes is not None else settings.jwt_ttl_minutes)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "iss": JWT_ISSUER,
        "typ": "session",
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": secrets.token_hex(8),
    }
    if password_hash:
        claims["pwf"] = password_fingerprint(password_hash)
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session expirée") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Jeton de session invalide") from exc
    if payload.get("typ") != "session":
        raise TokenError("Jeton de session invalide")
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except ValueError as exc:
        raise TokenError("Jeton de session invalide") from exc
    return TokenClaims(
        user_id=user_id,
        password_fingerprint=payload.get("pwf"),
        issued_at=datetime.fromtimestamp(int(payload["iat"]), UTC),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), UTC),
        token_id=str(payload.get("jti", "")),
    )


# --- Agent API keys -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeneratedApiKey:
    key: str  # full key, shown once
    prefix: str  # stored, unique
    key_hash: str  # stored (sha256 hex)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> GeneratedApiKey:
    prefix = "".join(secrets.choice(_PREFIX_ALPHABET) for _ in range(API_KEY_PREFIX_LENGTH))
    secret = "".join(secrets.choice(_BASE62) for _ in range(API_KEY_SECRET_LENGTH))
    key = f"{API_KEY_SCHEME}_{prefix}_{secret}"
    return GeneratedApiKey(key=key, prefix=prefix, key_hash=hash_api_key(key))


def looks_like_api_key(token: str | None) -> bool:
    return bool(token) and str(token).startswith(f"{API_KEY_SCHEME}_")


def parse_api_key(key: str) -> tuple[str, str] | None:
    """Return ``(prefix, secret)`` for a well-formed key, ``None`` otherwise."""
    parts = key.strip().split("_")
    if len(parts) != 3 or parts[0] != API_KEY_SCHEME:
        return None
    prefix, secret = parts[1], parts[2]
    if len(prefix) != API_KEY_PREFIX_LENGTH or len(secret) != API_KEY_SECRET_LENGTH:
        return None
    if not all(c in _PREFIX_ALPHABET for c in prefix) or not all(c in _BASE62 for c in secret):
        return None
    return prefix, secret


def verify_api_key(key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(key), stored_hash)


def mask_api_key(prefix: str) -> str:
    """Display form of a key: ``orb_ab12cd34_••••``."""
    return f"{API_KEY_SCHEME}_{prefix}_" + "•" * 4
