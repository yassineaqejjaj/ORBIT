"""Sliding-window rate limiting and progressive account lockout, backed by Valkey.

Limits are expressed as ``"5/minute,20/hour"`` (``ORBIT_RATE_LIMIT_*``). Each window is a sorted set
of request timestamps; a Lua script prunes, checks and records atomically across all windows of a
limit, so a rejected request is never counted.

When Valkey is unreachable the limiter *fails open* (the request is allowed and a warning is logged):
availability of the platform is preferred over throttling, and the argon2 cost still bounds brute force.
"""

from __future__ import annotations

import logging
import math
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from redis.exceptions import RedisError

from app.errors import ApiError

logger = logging.getLogger("orbit.ratelimit")

_UNITS: dict[str, int] = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "h": 3600,
    "hour": 3600,
    "d": 86400,
    "day": 86400,
}
_LIMIT_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)?\s*([a-z]+?)s?\s*$", re.IGNORECASE)

_SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local member = ARGV[2]
local record = ARGV[3] == '1'
local n = #KEYS
local retry = 0
for i = 1, n do
  local window = tonumber(ARGV[3 + (i - 1) * 2 + 1])
  local limit = tonumber(ARGV[3 + (i - 1) * 2 + 2])
  redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now - window)
  local count = redis.call('ZCARD', KEYS[i])
  if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
    local wait = window
    if oldest[2] then wait = tonumber(oldest[2]) + window - now end
    if wait > retry then retry = wait end
  end
end
if retry > 0 or not record then return retry end
for i = 1, n do
  local window = tonumber(ARGV[3 + (i - 1) * 2 + 1])
  redis.call('ZADD', KEYS[i], now, member)
  redis.call('PEXPIRE', KEYS[i], window)
end
return 0
"""

KEY_PREFIX = "orbit:rl"


@dataclass(frozen=True, slots=True)
class Limit:
    count: int
    window_seconds: int

    @property
    def label(self) -> str:
        return f"{self.count}/{self.window_seconds}s"


def parse_limits(spec: str) -> list[Limit]:
    """Parse ``"5/minute,20/hour"`` (also ``10/30s``, ``100/2h``). An empty spec disables limiting."""
    limits: list[Limit] = []
    for part in (item for item in spec.split(",") if item.strip()):
        match = _LIMIT_RE.match(part)
        if match is None:
            raise ValueError(
                f"Limite de débit invalide « {part.strip()} » (format attendu : 5/minute,20/hour)."
            )
        count, multiplier, unit = int(match.group(1)), int(match.group(2) or 1), match.group(3).lower()
        if unit not in _UNITS or count < 1 or multiplier < 1:
            raise ValueError(
                f"Limite de débit invalide « {part.strip()} » (unités : second, minute, hour, day)."
            )
        limits.append(Limit(count=count, window_seconds=_UNITS[unit] * multiplier))
    return limits


class RateLimited(ApiError):
    """429 with ``Retry-After`` (seconds) and a French message (``{delay}`` in ``detail`` is replaced)."""

    def __init__(self, retry_after: float, detail: str | None = None, *, code: str = "rate_limited") -> None:
        seconds = max(1, math.ceil(retry_after))
        template = detail or "Trop de requêtes : réessayez dans {delay}."
        super().__init__(
            429,
            template.replace("{delay}", _human_delay(seconds)),
            code=code,
            headers={"Retry-After": str(seconds)},
        )
        self.retry_after = seconds


def _human_delay(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} seconde{'s' if seconds > 1 else ''}"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} minutes"


def _client() -> Any:
    from app.memory.short_term import get_valkey

    return get_valkey()


async def _run(bucket: str, identity: str, spec: str, *, record: bool) -> float:
    limits = parse_limits(spec)
    if not limits:
        return 0.0
    now_ms = int(time.time() * 1000)
    keys = [f"{KEY_PREFIX}:{bucket}:{limit.window_seconds}:{identity}" for limit in limits]
    args: list[str | int] = [now_ms, uuid.uuid4().hex, "1" if record else "0"]
    for limit in limits:
        args.extend([limit.window_seconds * 1000, limit.count])
    try:
        retry_ms = await _client().eval(_SLIDING_WINDOW_LUA, len(keys), *keys, *args)
    except (RedisError, OSError) as exc:
        logger.warning("Rate limiting unavailable (Valkey error, failing open): %s", exc)
        return 0.0
    return max(0.0, float(retry_ms or 0) / 1000.0)


async def hit(bucket: str, identity: str, spec: str) -> float:
    """Record one request for ``bucket:identity``; return 0 when allowed, else the wait in seconds."""
    return await _run(bucket, identity, spec, record=True)


async def check(bucket: str, identity: str, spec: str) -> float:
    """Like :func:`hit` without recording anything (used to count failures only)."""
    return await _run(bucket, identity, spec, record=False)


def scaled(spec: str, factor: int) -> str:
    """``spec`` with every count multiplied by ``factor`` (coarser per-IP limit from a per-account one)."""
    return ",".join(f"{limit.count * factor}/{limit.window_seconds}s" for limit in parse_limits(spec))


async def enforce(bucket: str, identity: str, spec: str, *, detail: str | None = None) -> None:
    """Raise :class:`RateLimited` when ``identity`` exceeded ``spec`` in ``bucket``."""
    retry_after = await hit(bucket, identity, spec)
    if retry_after > 0:
        raise RateLimited(retry_after, detail)


# --- Progressive account lockout --------------------------------------------------------------------


def _lock_keys(account: str) -> tuple[str, str, str]:
    base = f"{KEY_PREFIX}:lock"
    return f"{base}:fails:{account}", f"{base}:level:{account}", f"{base}:until:{account}"


async def lockout_remaining(account: str) -> float:
    """Seconds left on the account lock (0 when not locked)."""
    _, _, until_key = _lock_keys(account)
    try:
        ttl_ms = await _client().pttl(until_key)
    except (RedisError, OSError) as exc:
        logger.warning("Account lockout unavailable (Valkey error, failing open): %s", exc)
        return 0.0
    return max(0.0, float(ttl_ms) / 1000.0) if ttl_ms and ttl_ms > 0 else 0.0


async def register_failure(account: str, *, threshold: int, base_seconds: int, max_seconds: int) -> float:
    """Count a failed attempt. Returns the lock duration applied (0 while under the threshold).

    Every ``threshold`` consecutive failures lock the account; each new lock doubles the previous
    one (``base``, ``2×base``, ``4×base`` … capped at ``max``). Counters expire after 24 h.
    """
    fails_key, level_key, until_key = _lock_keys(account)
    try:
        client = _client()
        fails = int(await client.incr(fails_key))
        await client.expire(fails_key, 86400)
        if fails < threshold:
            return 0.0
        level = int(await client.incr(level_key))
        await client.expire(level_key, 86400)
        await client.delete(fails_key)
        duration = min(max_seconds, base_seconds * (2 ** (level - 1)))
        await client.set(until_key, "1", ex=duration)
        return float(duration)
    except (RedisError, OSError) as exc:
        logger.warning("Account lockout unavailable (Valkey error, failing open): %s", exc)
        return 0.0


async def register_success(account: str) -> None:
    try:
        await _client().delete(*_lock_keys(account))
    except (RedisError, OSError) as exc:
        logger.warning("Account lockout reset failed (Valkey error): %s", exc)


async def reset_account(account: str) -> None:
    """Admin unlock (password reset / reactivation)."""
    await register_success(account)
