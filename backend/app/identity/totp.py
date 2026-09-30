"""TOTP (RFC 6238, HMAC-SHA1, 6 digits, 30 s) and recovery codes, implemented with the stdlib.

Verification accepts ±1 time step and refuses a step that is not strictly newer than the last
accepted one (replay protection). Recovery codes carry 60 bits of entropy and are stored as SHA-256.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

import segno

DIGITS = 6
PERIOD = 30
WINDOW = 1
ISSUER = "ORBIT"
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i


def generate_secret() -> str:
    """Base32 secret (160 bits, RFC 4226 recommendation), without padding."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def hotp(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**DIGITS)
    return str(code).zfill(DIGITS)


def current_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // PERIOD)


def totp(secret: str, at: float | None = None) -> str:
    return hotp(secret, current_step(at))


def verify(secret: str, code: str, *, last_step: int | None = None, at: float | None = None) -> int | None:
    """Return the matched time step when ``code`` is valid (±1 step, not replayed), else ``None``."""
    candidate = "".join(ch for ch in code if ch.isdigit())
    if len(candidate) != DIGITS:
        return None
    now = current_step(at)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(hotp(secret, step), candidate):
            return step
    return None


def otpauth_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    query = urlencode({"secret": secret, "issuer": ISSUER, "algorithm": "SHA1", "digits": DIGITS, "period": PERIOD})
    return f"otpauth://totp/{label}?{query}"


def qr_svg(uri: str) -> str:
    """Inline SVG of the provisioning URI (no external request, no JavaScript)."""
    qr = segno.make(uri, error="m")
    return str(qr.svg_inline(scale=4, border=2, dark="#111827", light="#ffffff"))


# --- Recovery codes --------------------------------------------------------------------------------


def _normalize_code(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(f"orbit-recovery:{_normalize_code(code)}".encode()).hexdigest()


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> tuple[list[str], list[str]]:
    """Return ``(codes shown once, hashes to store)``. Format ``xxxx-xxxx-xxxx``."""
    codes: list[str] = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes, [hash_recovery_code(code) for code in codes]


def consume_recovery_code(code: str, hashes: list[str]) -> list[str] | None:
    """Return the remaining hashes when ``code`` matches one of ``hashes``, else ``None``."""
    target = hash_recovery_code(code)
    for index, stored in enumerate(hashes):
        if hmac.compare_digest(str(stored), target):
            return [h for i, h in enumerate(hashes) if i != index]
    return None


def looks_like_totp(code: str) -> bool:
    stripped = code.replace(" ", "")
    return stripped.isdigit() and len(stripped) == DIGITS
