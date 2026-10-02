"""Webhook security helpers: secret encryption, HMAC signature and anti-SSRF URL checks."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import secrets
import socket
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.errors import ApiError

SECRET_PREFIX = "whsec_"
ENCRYPTION_MISSING = (
    "Le chiffrement des secrets n'est pas configuré : définissez ORBIT_ENCRYPTION_KEY "
    "(clé Fernet) pour utiliser les webhooks"
)


class UnsafeUrlError(ValueError):
    """The URL is not an acceptable webhook destination (French message)."""


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


def encryption_available() -> bool:
    try:
        _fernet()
    except ApiError:
        return False
    return True


def generate_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ApiError(
            503, "Secret de webhook illisible (clé de chiffrement modifiée ?)", code="secret_unreadable"
        ) from exc


def secret_hint(secret: str) -> str:
    return f"{secret[: len(SECRET_PREFIX) + 4]}…{secret[-4:]}"


def sign(secret: str, body: bytes) -> str:
    """Value of ``X-Orbit-Signature``: ``sha256=<hex HMAC-SHA256(secret, body)>``."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- Anti-SSRF ----------------------------------------------------------------------------------------


def _dev() -> bool:
    return settings.env == "development"


def check_url_syntax(url: str) -> tuple[str, int]:
    """Scheme/host checks. Returns ``(host, port)``."""
    parts = urlsplit(url.strip())
    allowed = ("https", "http") if _dev() else ("https",)
    if parts.scheme not in allowed:
        raise UnsafeUrlError(
            "L'URL du webhook doit utiliser HTTPS" if not _dev() else "L'URL doit commencer par http(s)://"
        )
    if not parts.hostname:
        raise UnsafeUrlError("L'URL du webhook doit contenir un nom d'hôte")
    if parts.username or parts.password:
        raise UnsafeUrlError("L'URL du webhook ne doit pas contenir d'identifiants")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("Port de l'URL invalide") from exc
    return parts.hostname, port


async def resolve_host(host: str, port: int) -> list[str]:
    """IP addresses of ``host`` (monkeypatched in tests)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_forbidden_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


async def check_destination(url: str) -> None:
    """Refuse private, loopback and link-local destinations after DNS resolution (except in development)."""
    host, port = check_url_syntax(url)
    if _dev():
        return
    try:
        addresses = [str(ipaddress.ip_address(host))]  # literal IP: no resolution
    except ValueError:
        addresses = []
    try:
        addresses = addresses or await resolve_host(host, port)
    except OSError as exc:
        raise UnsafeUrlError(f"Nom d'hôte introuvable : {host}") from exc
    if not addresses:
        raise UnsafeUrlError(f"Nom d'hôte introuvable : {host}")
    if any(is_forbidden_ip(address) for address in addresses):
        raise UnsafeUrlError(
            "Destination refusée : adresse privée, loopback ou link-local (protection anti-SSRF)"
        )
