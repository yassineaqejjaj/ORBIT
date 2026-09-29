"""Non-leak rules applied when context data is shown to someone (ARCHITECTURE §3).

The governance verdicts are computed for the *effective* identity of a request (the user an agent
acts for, bounded by the agent's clearance). What a *viewer* may see of the result is decided here:

* ``full``      the viewer could read the underlying content themselves;
* ``partial``   owners/admins who could not read it: title and id only (audit), never the excerpt;
* ``redacted``  nothing but the candidate type and the reason (``redacted: true``).

This applies to the ``POST /context`` response (viewer = the calling human or agent, never the
``on_behalf_of`` user), to reconstituted requests and to snapshots read later by other members.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from app.enums import MemoryScope
from app.governance.acl import acl_allows, effective_principals, user_principal

if TYPE_CHECKING:
    from app.deps import ProjectAccess

RESTRICTED_TITLE = "Contenu restreint"
FORGOTTEN_TEXT = "[oublié]"
REDACTED_ACL_DETAIL = "accès non autorisé — détails caviardés"


class Visibility(StrEnum):
    full = "full"
    partial = "partial"
    redacted = "redacted"


@dataclass(frozen=True, slots=True)
class Viewer:
    principals: frozenset[str]
    clearance: int
    user_id: uuid.UUID | None
    sees_restricted_details: bool
    is_admin: bool
    is_agent: bool = False

    @classmethod
    def from_access(cls, access: ProjectAccess) -> Viewer:
        principal = access.principal
        return cls(
            principals=frozenset(effective_principals(access)),
            clearance=int(principal.clearance),
            user_id=principal.user_id,
            sees_restricted_details=principal.is_user and access.can_see_restricted_details,
            is_admin=principal.is_user and principal.is_admin,
            is_agent=principal.is_agent,
        )

    def can_read(
        self,
        *,
        classification: int,
        acls: Sequence[Sequence[str] | None],
        memory_scope: MemoryScope | str | None = None,
        subject_user_id: uuid.UUID | str | None = None,
    ) -> bool:
        if self.is_admin:
            return True
        if int(classification) > self.clearance:
            return False
        is_user_memory = memory_scope is not None and str(getattr(memory_scope, "value", memory_scope)) == "user"
        if is_user_memory:
            if subject_user_id is None or self.user_id is None or str(subject_user_id) != str(self.user_id):
                return False
        subject = user_principal(subject_user_id) if (is_user_memory and subject_user_id) else None
        for acl in acls:
            if acl_allows(acl, self.principals):
                continue
            if subject is not None and acl and all(entry == subject for entry in acl):
                continue  # personal memory of the viewer (checked above)
            return False
        return True

    def visibility(
        self,
        *,
        classification: int,
        acls: Sequence[Sequence[str] | None],
        memory_scope: MemoryScope | str | None = None,
        subject_user_id: uuid.UUID | str | None = None,
    ) -> Visibility:
        if self.can_read(
            classification=classification, acls=acls, memory_scope=memory_scope, subject_user_id=subject_user_id
        ):
            return Visibility.full
        return Visibility.partial if self.sees_restricted_details else Visibility.redacted


def redact_markdown(markdown: str, citations: Mapping[str, str]) -> str:
    """Replace the bullet and the source line of each citation by ``citations[citation]``
    (e.g. « Contenu restreint », « [oublié] »). Other lines are untouched."""
    if not citations:
        return markdown
    lines = markdown.split("\n")
    for index, line in enumerate(lines):
        stripped = line.rstrip()
        bullet = re.search(r"\[(S\d+)\]$", stripped)
        if bullet and stripped.startswith("- ") and bullet.group(1) in citations:
            lines[index] = f"- {citations[bullet.group(1)]} [{bullet.group(1)}]"
            continue
        source = re.match(r"^\[(S\d+)\] ", stripped)
        if source and source.group(1) in citations:
            lines[index] = f"[{source.group(1)}] {citations[source.group(1)]}"
    return "\n".join(lines)
