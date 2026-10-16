"""ORION access-token claims contract (ADR 001 §3-§4, NOV-104): validation and claims -> role / clearance.

SELF-CONTAINED ON PURPOSE. Standard library only, no import from this repository: the file is copied byte for byte
into ORBIT and FORGE (``docs/CONTRACTS.md`` § "Claims contract"), and each copy is verified against the sha256 in
``contracts/claims/manifest.json``. Never edit a copy: change it here, regenerate the fixtures, refresh the copies.

What it does, in this order, for one token and one service:

1. validate the JWT: ``RS256`` only, signature against a JWKS the caller supplies (no network here), then ``iss``,
   ``aud``, ``exp`` and, when present, ``nbf``; typed claims of the contract that are present but malformed reject the
   token (a malformed ``orion_clearance`` must never be read as "no cap"); unknown claims are ignored;
2. extract the claims into :class:`Claims`;
3. apply the ADR §4 rules of the service reading the token (:func:`evaluate`):
   ``effective_clearance = min(local clearance, orion_clearance)`` (an absent claim never gives more than the local
   value), realm roles of *this* service's prefix only, a token without ``orion_workspace_id`` opens no space resource.

The token never grants a right on its own: every function takes the *local* state (clearance, role) of the service.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

CONTRACT_VERSION = 1

#: service -> expected ``aud`` (ADR §4, first row)
AUDIENCES: dict[str, str] = {"nova": "nova-web", "orbit": "orbit", "forge": "forge"}
#: service -> prefix of the realm roles it reads (``<service>-<role>``); roles of another prefix never count
ROLE_PREFIXES: dict[str, str] = {"nova": "nova-", "orbit": "orbit-", "forge": "forge-"}
#: FORGE global roles, lowest first (``viewer < evaluator < editor < maintainer < admin``)
FORGE_ROLES: tuple[str, ...] = ("viewer", "evaluator", "editor", "maintainer", "admin")
#: ORBIT / NOVA project roles, lowest first (membership stays local: a realm role never grants one)
PROJECT_ROLES: tuple[str, ...] = ("viewer", "editor", "owner")

MIN_RSA_BITS = 2048
#: ADR §3/§6: a delegated token (carrying ``act``) is short-lived; longer than this is refused
DELEGATED_MAX_LIFETIME = 900

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
#: DER ``DigestInfo`` prefix of SHA-256 (RFC 8017 §9.2, note 1)
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


class ClaimsError(Exception):
    """The token is refused. ``code`` is stable (``expired``, ``invalid_audience``, ``invalid_claim:<name>``...)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- JWT / RS256 (public-key verification only) -----------------------------------------------------------------


def _b64url_decode(part: str) -> bytes:
    if not part or not re.fullmatch(r"[A-Za-z0-9_-]+", part):
        raise ClaimsError("malformed_token")
    try:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ClaimsError("malformed_token") from exc


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ClaimsError("malformed_token") from exc
    if not isinstance(value, dict):
        raise ClaimsError("malformed_token")
    return value


def _public_numbers(jwk: Mapping[str, Any]) -> tuple[int, int]:
    try:
        n = int.from_bytes(_b64url_decode(str(jwk["n"])), "big")
        e = int.from_bytes(_b64url_decode(str(jwk["e"])), "big")
    except (KeyError, ClaimsError) as exc:
        raise ClaimsError("unknown_key") from exc
    # 65537 only: with the exact-match padding check below it is the one exponent every IdP uses
    if n.bit_length() < MIN_RSA_BITS or e != 65537:
        raise ClaimsError("unknown_key")
    return n, e


def _select_key(jwks: Mapping[str, Any], kid: Any) -> tuple[int, int]:
    keys = jwks.get("keys") if isinstance(jwks, Mapping) else None
    if not isinstance(keys, Sequence) or isinstance(keys, str):
        raise ClaimsError("unknown_key")
    usable = [
        k
        for k in keys
        if isinstance(k, Mapping) and k.get("kty") == "RSA" and k.get("use", "sig") == "sig" and k.get("alg", "RS256") == "RS256"
    ]
    if kid is None:
        if len(usable) != 1:  # no kid: only unambiguous when the set has exactly one candidate
            raise ClaimsError("unknown_key")
        return _public_numbers(usable[0])
    if not isinstance(kid, str):
        raise ClaimsError("malformed_token")
    for key in usable:
        if key.get("kid") == kid:
            return _public_numbers(key)
    raise ClaimsError("unknown_key")


def _verify_rs256(signing_input: bytes, signature: bytes, n: int, e: int) -> bool:
    """RSASSA-PKCS1-v1_5 / SHA-256. The whole encoded message is compared (no padding parsing: no forgery by lax parsing)."""
    size = (n.bit_length() + 7) // 8
    if len(signature) != size:
        return False
    value = int.from_bytes(signature, "big")
    if value >= n:
        return False
    digest_info = _SHA256_DIGEST_INFO + hashlib.sha256(signing_input).digest()
    if size < len(digest_info) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (size - len(digest_info) - 3) + b"\x00" + digest_info
    return hmac.compare_digest(pow(value, e, n).to_bytes(size, "big"), expected)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _string_list(value: Any, claim: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ClaimsError(f"invalid_claim:{claim}")
    return tuple(value)


# --- Claims -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Actor:
    """``act`` (RFC 8693): who acts on behalf of ``Claims.subject``. The audit trail keeps both."""

    subject: str
    client_id: str | None = None


@dataclass(frozen=True)
class Claims:
    """The claims of a *validated* token that the contract defines (everything else is dropped)."""

    subject: str
    issuer: str
    audience: tuple[str, ...]
    issued_at: int | float
    expires_at: int | float
    not_before: int | float | None = None
    email: str | None = None
    email_verified: bool = False
    name: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    realm_roles: tuple[str, ...] = ()
    clearance: int | None = None
    actor: Actor | None = None
    scopes: tuple[str, ...] = ()
    amr: tuple[str, ...] = ()
    preferred_username: str | None = None

    @property
    def is_service(self) -> bool:
        """A client-credentials token (Keycloak names its service-account users ``service-account-<client>``)."""
        return (self.preferred_username or "").startswith("service-account-")

    @property
    def email_matchable(self) -> bool:
        """The e-mail may seed the account matching of ADR §8 only when the IdP verified it."""
        return bool(self.email) and self.email_verified is True

    @property
    def mfa(self) -> bool:
        return "mfa" in self.amr

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def roles_for(self, service: str) -> frozenset[str]:
        """Role names (prefix removed) of the realm roles of ``service``; other prefixes are ignored (ADR §3)."""
        prefix = ROLE_PREFIXES[service]
        return frozenset(r[len(prefix) :] for r in self.realm_roles if r.startswith(prefix) and len(r) > len(prefix))


def _optional_str(payload: Mapping[str, Any], name: str) -> str | None:
    if name not in payload or payload[name] is None:
        return None
    if not isinstance(payload[name], str):
        raise ClaimsError(f"invalid_claim:{name}")
    return payload[name]


def _uuid(payload: Mapping[str, Any], name: str) -> str | None:
    value = _optional_str(payload, name)
    if value is not None and not _UUID.match(value):
        raise ClaimsError(f"invalid_claim:{name}")
    return value.lower() if value else None


def parse_claims(payload: Mapping[str, Any]) -> Claims:
    """Extract the contract claims from a payload whose signature, issuer, audience and times were already checked."""
    for name in ("sub", "iss", "aud", "exp", "iat"):
        if name not in payload:
            raise ClaimsError(f"missing_claim:{name}")
    subject, issuer = payload["sub"], payload["iss"]
    for name, value in (("sub", subject), ("iss", issuer)):
        if not isinstance(value, str) or not value:
            raise ClaimsError(f"invalid_claim:{name}")
    raw_aud = payload["aud"]
    audience = (raw_aud,) if isinstance(raw_aud, str) else _string_list(raw_aud, "aud")
    for name in ("exp", "iat"):
        if not _is_number(payload[name]):
            raise ClaimsError(f"invalid_claim:{name}")
    if "nbf" in payload and not _is_number(payload["nbf"]):
        raise ClaimsError("invalid_claim:nbf")
    email_verified = payload.get("email_verified", False)
    if not isinstance(email_verified, bool):
        raise ClaimsError("invalid_claim:email_verified")
    clearance = payload.get("orion_clearance")
    if "orion_clearance" in payload and (
        isinstance(clearance, bool) or not isinstance(clearance, int) or not 0 <= clearance <= 3
    ):
        raise ClaimsError("invalid_claim:orion_clearance")  # present but unreadable: refuse, never "no cap"
    roles: tuple[str, ...] = ()
    if "realm_access" in payload:
        access = payload["realm_access"]
        if not isinstance(access, dict) or ("roles" in access and not isinstance(access["roles"], list)):
            raise ClaimsError("invalid_claim:realm_access.roles")
        roles = _string_list(access.get("roles", []), "realm_access.roles")
    actor = None
    if "act" in payload:
        act = payload["act"]
        if not isinstance(act, dict) or not isinstance(act.get("sub"), str) or not act["sub"]:
            raise ClaimsError("invalid_claim:act")
        if act.get("client_id") is not None and not isinstance(act["client_id"], str):
            raise ClaimsError("invalid_claim:act")
        actor = Actor(subject=act["sub"], client_id=act.get("client_id"))
        if payload["exp"] - payload["iat"] > DELEGATED_MAX_LIFETIME:
            raise ClaimsError("delegated_token_too_long")
    workspace_id, project_id = _uuid(payload, "orion_workspace_id"), _uuid(payload, "orion_project_id")
    scope = payload.get("scope", [])
    scopes = tuple(scope.split()) if isinstance(scope, str) else _string_list(scope, "scope")
    amr = _string_list(payload["amr"], "amr") if "amr" in payload else ()
    return Claims(
        subject=subject,
        issuer=issuer,
        audience=audience,
        issued_at=payload["iat"],
        expires_at=payload["exp"],
        not_before=payload.get("nbf"),
        email=_optional_str(payload, "email"),
        email_verified=email_verified,
        name=_optional_str(payload, "name"),
        workspace_id=workspace_id,
        # a project means nothing outside a space: without a workspace the project id is dropped
        project_id=project_id if workspace_id else None,
        realm_roles=roles,
        clearance=clearance,
        actor=actor,
        scopes=scopes,
        amr=amr,
        preferred_username=_optional_str(payload, "preferred_username"),
    )


def validate_token(
    token: str,
    jwks: Mapping[str, Any],
    *,
    issuer: str,
    audience: str,
    now: float | None = None,
    leeway: float = 0,
) -> Claims:
    """Verify ``token`` (signature, ``iss``, ``aud``, ``exp``, ``nbf``) and return its claims, or raise :class:`ClaimsError`.

    ``jwks`` is supplied by the caller (fetched and cached by the service; this module never does I/O). ``now`` is an
    epoch in seconds (default: the clock). ``leeway`` tolerates clock skew on ``exp`` / ``nbf`` (default: none).
    """
    if not isinstance(token, str) or token.count(".") != 2:
        raise ClaimsError("malformed_token")
    head, body, sig = token.split(".")
    header = _json_object(_b64url_decode(head))
    if header.get("alg") != "RS256":  # also refuses "none" and HS256 signed with the public key as secret
        raise ClaimsError("unsupported_alg")
    if "crit" in header:
        raise ClaimsError("unsupported_header")
    n, e = _select_key(jwks, header.get("kid"))
    if not _verify_rs256(f"{head}.{body}".encode("ascii"), _b64url_decode(sig), n, e):
        raise ClaimsError("bad_signature")
    payload = _json_object(_b64url_decode(body))
    claims = parse_claims(payload)
    if claims.issuer != issuer:
        raise ClaimsError("invalid_issuer")
    if audience not in claims.audience:
        raise ClaimsError("invalid_audience")
    moment = time.time() if now is None else now
    if moment >= claims.expires_at + leeway:
        raise ClaimsError("expired")
    if claims.not_before is not None and moment + leeway < claims.not_before:
        raise ClaimsError("not_yet_valid")
    return claims


# --- ADR §4: claims -> role and clearance ---------------------------------------------------------------------


def effective_clearance(local: int, claim: int | None) -> int:
    """``min(local clearance, orion_clearance)``; an absent claim returns the local value, never more."""
    if isinstance(local, bool) or not isinstance(local, int) or not 0 <= local <= 3:
        raise ValueError("local clearance must be an integer 0-3")
    return local if claim is None else min(local, claim)


def cap_role(local_role: str | None, realm_role: str | None, ladder: Sequence[str]) -> str | None:
    """Local role capped by the realm role when there is one; no local role stays no role (the token grants nothing)."""
    if local_role is None:
        return None
    if local_role not in ladder:
        raise ValueError(f"unknown local role {local_role!r}")
    if realm_role is None:
        return local_role
    return ladder[min(ladder.index(local_role), ladder.index(realm_role))]


def can_open_space_resource(claims: Claims | None, resource_workspace_id: str | None) -> bool:
    """A resource of a workspace opens only for a token carrying that very ``orion_workspace_id`` (ADR §9)."""
    if claims is None or not claims.workspace_id or not resource_workspace_id:
        return False
    return claims.workspace_id == resource_workspace_id.lower()


def can_open_project(claims: Claims | None, resource_workspace_id: str | None, resource_project_id: str | None) -> bool:
    """A token that names a project opens that project only (and only inside its workspace); membership stays local."""
    if not can_open_space_resource(claims, resource_workspace_id) or claims is None:
        return False
    return claims.project_id is None or (resource_project_id is not None and claims.project_id == resource_project_id.lower())


@dataclass(frozen=True)
class Decision:
    """What one service concludes from one token and its local state. All fields have a refusal value."""

    valid: bool
    error: str | None = None
    subject: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    space_access: bool = False  # False: no space resource may be opened with this token
    platform_admin: bool = False
    role: str | None = None  # functional role (see ``evaluate``); None: the token grants none
    effective_clearance: int | None = None
    mfa: bool = False
    email_matchable: bool = False
    delegated_by: str | None = None  # ``act.sub``
    is_service: bool = False
    scopes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "error": self.error,
            "subject": self.subject,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "space_access": self.space_access,
            "platform_admin": self.platform_admin,
            "role": self.role,
            "effective_clearance": self.effective_clearance,
            "mfa": self.mfa,
            "email_matchable": self.email_matchable,
            "delegated_by": self.delegated_by,
            "is_service": self.is_service,
            "scopes": list(self.scopes),
        }


def decide(claims: Claims, service: str, *, local_clearance: int, local_role: str | None = None) -> Decision:
    """Apply the ADR §4 table of ``service`` to validated claims.

    * ``platform_admin``: NOVA / ORBIT: the ``<service>-admin`` realm role. FORGE: the capped role is ``admin``.
    * ``role``: NOVA / ORBIT: the local project role, unchanged (no realm role grants or lowers a project role).
      FORGE: the local global role capped by the highest ``forge-*`` realm role (never raised; no local account, no role).
    * ``effective_clearance``: ``min(local_clearance, orion_clearance)``; ``local_clearance`` is the caller's local
      value or its default (NOVA: ``DEFAULT_CLEARANCE``), so an absent claim never gives more than that.
    """
    if service not in AUDIENCES:
        raise ValueError(f"unknown service {service!r}")
    realm = claims.roles_for(service)
    admin = "admin" in realm
    if service == "forge":
        held = [r for r in FORGE_ROLES if r in realm]
        role = cap_role(local_role, held[-1] if held else None, FORGE_ROLES)
        admin = role == "admin"
    else:
        role = cap_role(local_role, None, PROJECT_ROLES)
    return Decision(
        valid=True,
        subject=claims.subject,
        workspace_id=claims.workspace_id,
        project_id=claims.project_id,
        space_access=claims.workspace_id is not None,
        platform_admin=admin,
        role=role,
        effective_clearance=effective_clearance(local_clearance, claims.clearance),
        mfa=claims.mfa,
        email_matchable=claims.email_matchable,
        delegated_by=claims.actor.subject if claims.actor else None,
        is_service=claims.is_service,
        scopes=claims.scopes,
    )


def evaluate(
    token: str,
    jwks: Mapping[str, Any],
    *,
    service: str,
    issuer: str,
    local_clearance: int,
    local_role: str | None = None,
    now: float | None = None,
    leeway: float = 0,
) -> Decision:
    """:func:`validate_token` then :func:`decide`; an invalid token yields a refused :class:`Decision` (never raises)."""
    if service not in AUDIENCES:
        raise ValueError(f"unknown service {service!r}")
    try:
        claims = validate_token(token, jwks, issuer=issuer, audience=AUDIENCES[service], now=now, leeway=leeway)
    except ClaimsError as exc:
        return Decision(valid=False, error=exc.code)
    return decide(claims, service, local_clearance=local_clearance, local_role=local_role)
