"""Password hashing, session tokens and agent API keys."""

from __future__ import annotations

import re
import uuid

import jwt
import pytest

from app.config import settings
from app.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    looks_like_api_key,
    parse_api_key,
    password_fingerprint,
    verify_api_key,
    verify_password,
)

API_KEY_PATTERN = re.compile(r"^orb_[a-z0-9]{8}_[A-Za-z0-9]{32}$")


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("S3cret-passphrase")
    assert hashed.startswith("$argon2id$")
    assert verify_password("S3cret-passphrase", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, password_hash="$argon2id$fake")
    claims = decode_access_token(token)
    assert claims.user_id == user_id
    assert claims.password_fingerprint == password_fingerprint("$argon2id$fake")
    assert claims.expires_at > claims.issued_at


def test_expired_and_tampered_tokens_are_rejected() -> None:
    expired = create_access_token(uuid.uuid4(), ttl_minutes=-1)
    with pytest.raises(TokenError, match="expirée"):
        decode_access_token(expired)
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "session", "iss": "orbit", "iat": 0, "exp": 9999999999}, "another-secret-of-sufficient-length-0123456789"
    )
    with pytest.raises(TokenError):
        decode_access_token(forged)
    wrong_type = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "refresh", "iss": "orbit", "iat": 0, "exp": 9999999999},
        settings.jwt_secret,
    )
    with pytest.raises(TokenError):
        decode_access_token(wrong_type)


def test_api_key_generation_and_verification() -> None:
    key = generate_api_key()
    assert API_KEY_PATTERN.match(key.key)
    assert key.key.split("_")[1] == key.prefix
    assert key.key_hash == hash_api_key(key.key)
    assert len(key.key_hash) == 64
    assert verify_api_key(key.key, key.key_hash)
    assert not verify_api_key(key.key + "x", key.key_hash)
    assert parse_api_key(key.key) == (key.prefix, key.key.split("_")[2])
    assert looks_like_api_key(key.key)
    assert not looks_like_api_key("eyJhbGciOi")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "orb_",
        "orb_short_secret",
        "orx_abcdefgh_" + "a" * 32,
        "orb_ABCDEFGH_" + "a" * 32,
        "orb_abcdefgh_" + "a" * 31,
    ],
)
def test_malformed_api_keys(value: str) -> None:
    assert parse_api_key(value) is None


def test_api_keys_are_unique() -> None:
    keys = {generate_api_key().key for _ in range(200)}
    assert len(keys) == 200
