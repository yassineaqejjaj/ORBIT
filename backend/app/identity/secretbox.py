"""Small authenticated-encryption helper for identity secrets stored in Postgres (TOTP seeds).

AES-256-GCM with a sub-key derived by HKDF-SHA256 from the master key ``ORBIT_ENCRYPTION_KEY``
(or ``ORBIT_ENCRYPTION_KEY_FILE``); previous master keys (``ORBIT_ENCRYPTION_PREVIOUS_KEYS``) are
accepted for decryption. Outside production, when no master key is configured, the sub-key is
derived from ``ORBIT_JWT_SECRET`` so development and tests work without extra setup.
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

_VERSION = "v1"
_INFO = b"orbit/identity-secret/v1"


class SecretBoxError(Exception):
    """Ciphertext cannot be decrypted with any configured key."""


def _master_keys() -> list[bytes]:
    keys: list[bytes] = []
    if settings.encryption_key:
        keys.append(base64.b64decode(settings.encryption_key.strip()))
    elif settings.encryption_key_file and Path(settings.encryption_key_file).is_file():
        keys.append(base64.b64decode(Path(settings.encryption_key_file).read_text().strip()))
    keys.extend(
        base64.b64decode(item.strip())
        for item in settings.encryption_previous_keys.split(",")
        if item.strip()
    )
    if not keys:
        keys.append(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return keys


@lru_cache(maxsize=16)
def _derive(master: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(master)


def encrypt(plaintext: str) -> str:
    key = _derive(_master_keys()[0])
    nonce = os.urandom(12)
    sealed = AESGCM(key).encrypt(nonce, plaintext.encode(), _INFO)
    return f"{_VERSION}:{base64.urlsafe_b64encode(nonce + sealed).decode()}"


def decrypt(token: str) -> str:
    version, _, payload = token.partition(":")
    if version != _VERSION or not payload:
        raise SecretBoxError("format de secret inconnu")
    raw = base64.urlsafe_b64decode(payload.encode())
    nonce, sealed = raw[:12], raw[12:]
    for master in _master_keys():
        try:
            return AESGCM(_derive(master)).decrypt(nonce, sealed, _INFO).decode()
        except InvalidTag:
            continue
    raise SecretBoxError("secret indéchiffrable avec les clés configurées")
