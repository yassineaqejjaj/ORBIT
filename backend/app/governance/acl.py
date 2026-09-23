"""Content ACL evaluation (ARCHITECTURE §3).

ACL entries (``acl_principals: text[]`` on documents, chunks, memory items):

* ``project:*``            every member of the project (default)
* ``role:owner`` / ``role:editor`` / ``role:viewer``   members having *at least* that role
* ``user:<uuid>``           a named user

A caller satisfies an ACL when its principal set intersects it. Principal sets are built by
:func:`effective_principals`: an owner carries ``role:owner``, ``role:editor`` and ``role:viewer`` so
that ``role:editor`` matches editors *and* owners, while ``role:owner`` only matches owners.

Agents without ``on_behalf_of`` only carry ``project:*``. An agent (or a human simulating another
user in the Explorer) acting on behalf of a member carries that member's principals.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from app.enums import ROLE_RANK, Role

if TYPE_CHECKING:
    from app.deps import ProjectAccess
    from app.models import Agent, User

PROJECT_ALL = "project:*"
DEFAULT_ACL: tuple[str, ...] = (PROJECT_ALL,)

_ROLE_ENTRY = re.compile(r"^role:(owner|editor|viewer)$")
_USER_ENTRY = re.compile(r"^user:([0-9a-fA-F-]{36})$")

#: Role principals carried by each role (supersets: owner ⊃ editor ⊃ viewer).
ROLE_PRINCIPALS: dict[Role, frozenset[str]] = {
    role: frozenset(f"role:{r.value}" for r in Role if ROLE_RANK[r] <= ROLE_RANK[role]) for role in Role
}


def user_principal(user_id: uuid.UUID | str) -> str:
    return f"user:{user_id}"


def role_principals(role: Role | str | None) -> frozenset[str]:
    if role is None:
        return frozenset()
    return ROLE_PRINCIPALS[Role(role)]


def principals_for_member(user_id: uuid.UUID | None, role: Role | str | None) -> set[str]:
    """Principal set of a project member (``project:*`` + role principals + ``user:<id>``)."""
    principals: set[str] = {PROJECT_ALL}
    principals |= role_principals(role)
    if user_id is not None:
        principals.add(user_principal(user_id))
    return principals


def effective_principals(
    access: ProjectAccess,
    on_behalf_of_user: User | None = None,
    role: Role | str | None = None,
) -> set[str]:
    """Principal set used to evaluate content ACLs for a request.

    * Human caller, no ``on_behalf_of``: the caller's own principals (role from ``access.role``;
      platform admins are owners everywhere).
    * ``on_behalf_of_user`` given (agent acting for a member, or a human simulating a member): that
      user's principals. ``role`` must be that user's role in the project; when unknown it defaults
      to ``viewer`` (least privilege). The caller is responsible for checking that the user is a member.
    * Agent without ``on_behalf_of``: ``{"project:*"}`` only.
    """
    if on_behalf_of_user is not None:
        return principals_for_member(on_behalf_of_user.id, role or Role.viewer)
    principal = access.principal
    if principal.kind == "agent" or principal.user is None:
        return {PROJECT_ALL}
    return principals_for_member(principal.user.id, access.role)


def acl_allows(acl_principals: Sequence[str] | None, principal_set: Iterable[str]) -> bool:
    """True when the caller holds at least one ACL entry. An empty ACL grants nothing (deny by default)."""
    if not acl_principals:
        return False
    held = principal_set if isinstance(principal_set, set | frozenset) else set(principal_set)
    return any(entry in held for entry in acl_principals)


def effective_clearance(
    user: User | None,
    agent: Agent | None,
    max_classification: int | None = None,
) -> int:
    """``min(user clearance, agent clearance, requested ceiling)`` over the values provided (0 if none)."""
    levels: list[int] = []
    if user is not None:
        levels.append(int(user.clearance))
    if agent is not None:
        levels.append(int(agent.clearance))
    if max_classification is not None:
        levels.append(int(max_classification))
    if not levels:
        return 0
    return max(0, min(3, min(levels)))


def classification_allowed(classification: int, clearance: int) -> bool:
    return int(classification) <= int(clearance)


def is_restricted(acl_principals: Sequence[str] | None) -> bool:
    """An ACL is restricted when it does not grant access to every project member."""
    return PROJECT_ALL not in (acl_principals or ())


def merge_acls(acls: Iterable[Sequence[str] | None]) -> list[str]:
    """Most restrictive combination of source ACLs for a derived item (§3).

    Unrestricted sources (``project:*``) do not narrow access. With one restricted source the item
    inherits its principals; with several, only the principals common to all of them are kept.
    """
    restricted = [set(acl) for acl in acls if acl and is_restricted(acl)]
    if not restricted:
        return [PROJECT_ALL]
    common = set.intersection(*restricted)
    return sorted(common)


def merge_classifications(levels: Iterable[int]) -> int:
    """Derived items take the highest classification of their sources."""
    return max((int(level) for level in levels), default=0)


def validate_acl_principals(values: Iterable[str] | None) -> list[str]:
    """Normalise and validate ACL entries (strip, de-duplicate, keep order). Raises ``ValueError`` (FR)."""
    if values is None:
        return list(DEFAULT_ACL)
    result: list[str] = []
    for raw in values:
        entry = str(raw).strip()
        if not entry:
            continue
        if entry == PROJECT_ALL or _ROLE_ENTRY.match(entry):
            normalised = entry
        else:
            match = _USER_ENTRY.match(entry)
            if not match:
                raise ValueError(
                    f"Principal d'ACL invalide « {entry} » "
                    "(attendu : project:*, role:owner|editor|viewer ou user:<uuid>)"
                )
            try:
                normalised = user_principal(uuid.UUID(match.group(1)))
            except ValueError as exc:
                raise ValueError(f"Identifiant utilisateur invalide dans l'ACL « {entry} »") from exc
        if normalised not in result:
            result.append(normalised)
    if not result:
        raise ValueError("L'ACL doit contenir au moins un principal (par défaut : project:*)")
    return result


def parse_acl_csv(raw: str | None) -> list[str] | None:
    """Parse the CSV form used by multipart endpoints (``"role:editor,user:…"``). ``None`` if empty."""
    if raw is None or not raw.strip():
        return None
    return validate_acl_principals(part for part in raw.split(","))


def acl_terms_filter(principal_set: Iterable[str]) -> dict[str, object]:
    """OpenSearch filter clause restricting hits to documents readable by ``principal_set``."""
    return {"terms": {"acl_principals": sorted(set(principal_set))}}
