"""Who may see which memory item (ARCHITECTURE §3, §8).

A memory item is visible to a caller of a project when **all** of the following hold:

* it belongs to the project, or it is organisation-wide long-term memory (``project_id IS NULL``);
* its classification is ≤ the caller's clearance;
* its ACL intersects the caller's principal set (:func:`app.governance.acl.effective_principals`);
* for ``scope = user``: the caller *is* the subject. User memory is private to its subject, even for
  project owners and platform admins (they only see aggregated counts elsewhere).

The same rules exist as a SQL clause (listing, counting, graph) and as a Python predicate (detail
and mutation endpoints, relation targets).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.types import Text

from app.enums import MemoryScope
from app.governance.acl import acl_allows, effective_principals
from app.models import MemoryItem

if TYPE_CHECKING:
    from app.deps import ProjectAccess


@dataclass(frozen=True, slots=True)
class MemoryViewer:
    """Resolved visibility parameters of a caller within a project."""

    project_id: uuid.UUID
    principals: frozenset[str]
    clearance: int
    user_id: uuid.UUID | None

    @classmethod
    def from_access(cls, access: ProjectAccess) -> MemoryViewer:
        principal = access.principal
        return cls(
            project_id=access.project_id,
            principals=frozenset(effective_principals(access)),
            clearance=int(principal.clearance),
            user_id=principal.user_id,
        )


def visibility_clause(viewer: MemoryViewer) -> ColumnElement[bool]:
    """SQL condition selecting the memory items visible to ``viewer`` (any version)."""
    in_scope = or_(
        MemoryItem.project_id == viewer.project_id,
        and_(MemoryItem.project_id.is_(None), MemoryItem.scope == MemoryScope.long_term),
    )
    principals = sorted(viewer.principals) or ["__none__"]
    conditions: list[ColumnElement[bool]] = [
        in_scope,
        MemoryItem.classification <= viewer.clearance,
        MemoryItem.acl_principals.overlap(array(principals, type_=Text)),
    ]
    if viewer.user_id is None:
        conditions.append(MemoryItem.scope != MemoryScope.user)
    else:
        conditions.append(
            or_(MemoryItem.scope != MemoryScope.user, MemoryItem.subject_user_id == viewer.user_id)
        )
    return and_(*conditions)


def can_view(item: MemoryItem, viewer: MemoryViewer) -> bool:
    """Python equivalent of :func:`visibility_clause` for one loaded item."""
    if item.project_id is None:
        if MemoryScope(item.scope) != MemoryScope.long_term:
            return False
    elif item.project_id != viewer.project_id:
        return False
    if int(item.classification) > viewer.clearance:
        return False
    if not acl_allows(item.acl_principals, viewer.principals):
        return False
    if MemoryScope(item.scope) == MemoryScope.user:
        return viewer.user_id is not None and item.subject_user_id == viewer.user_id
    return True
