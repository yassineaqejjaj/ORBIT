"""Client IP resolution honouring ``ORBIT_TRUSTED_PROXIES``.

``X-Forwarded-For`` is only believed when the direct peer is a trusted proxy; the chain is then
walked right-to-left and the first address that is *not* a trusted proxy is the client. This
replaces uvicorn's ``--forwarded-allow-ips *`` (spoofable audit IPs, see audit finding
``deploy-proxy-trust-wildcard``).
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from starlette.requests import HTTPConnection

from app.config import settings

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def _networks(spec: str) -> tuple[IPNetwork, ...]:
    return tuple(ipaddress.ip_network(item.strip(), strict=False) for item in spec.split(",") if item.strip())


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = value.strip().strip('"')
    if candidate.startswith("[") and "]" in candidate:  # "[2001:db8::1]:443"
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1:  # "203.0.113.7:51234"
        candidate = candidate.split(":", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def is_trusted_proxy(address: str | None, spec: str | None = None) -> bool:
    if not address:
        return False
    ip = _parse_ip(address)
    if ip is None:
        return False
    return any(ip in network for network in _networks(spec if spec is not None else settings.trusted_proxies))


def resolve_client_ip(peer: str | None, forwarded_for: str | None, spec: str | None = None) -> str | None:
    """Return the real client address given the direct ``peer`` and the ``X-Forwarded-For`` header."""
    if not forwarded_for or not is_trusted_proxy(peer, spec):
        return peer
    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    for hop in reversed(hops):
        ip = _parse_ip(hop)
        if ip is None:
            return peer  # malformed chain: do not trust any of it
        if not is_trusted_proxy(str(ip), spec):
            return str(ip)
    return str(_parse_ip(hops[0])) if hops else peer


def client_ip(conn: HTTPConnection) -> str | None:
    """Client IP of a request/websocket (used by audit and rate limiting)."""
    peer = conn.client.host if conn.client else None
    return resolve_client_ip(peer, conn.headers.get("x-forwarded-for"))


def is_secure_request(conn: HTTPConnection) -> bool:
    """``https`` either directly or via ``X-Forwarded-Proto`` from a trusted proxy."""
    if conn.url.scheme == "https":
        return True
    peer = conn.client.host if conn.client else None
    proto = conn.headers.get("x-forwarded-proto", "")
    return is_trusted_proxy(peer) and proto.split(",")[0].strip().lower() == "https"
