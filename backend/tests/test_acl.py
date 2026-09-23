"""ACL and clearance helpers (pure functions)."""

from __future__ import annotations

import uuid

import pytest

from app.deps import Principal, ProjectAccess
from app.enums import Role
from app.governance.acl import (
    acl_allows,
    acl_terms_filter,
    effective_clearance,
    effective_principals,
    merge_acls,
    merge_classifications,
    parse_acl_csv,
    principals_for_member,
    validate_acl_principals,
)
from app.models import Agent, Project, User


def _user(clearance: int = 1, is_admin: bool = False) -> User:
    return User(
        id=uuid.uuid4(),
        email="u@example.com",
        full_name="U",
        password_hash="x",
        clearance=clearance,
        is_admin=is_admin,
    )


def _agent(project: Project, clearance: int = 1) -> Agent:
    return Agent(id=uuid.uuid4(), project_id=project.id, name="A", kind="product", clearance=clearance)


def _project() -> Project:
    return Project(id=uuid.uuid4(), slug="p", name="P", settings={})


def _access(role: Role, user: User | None = None, agent: Agent | None = None) -> ProjectAccess:
    principal = Principal.for_agent(agent) if agent is not None else Principal.for_user(user or _user())
    return ProjectAccess(project=_project(), principal=principal, role=role)


def test_owner_principals_include_lower_roles() -> None:
    user = _user()
    principals = effective_principals(_access(Role.owner, user))
    assert principals == {"project:*", "role:viewer", "role:editor", "role:owner", f"user:{user.id}"}


def test_role_hierarchy_matching() -> None:
    viewer = effective_principals(_access(Role.viewer))
    editor = effective_principals(_access(Role.editor))
    owner = effective_principals(_access(Role.owner))
    assert not acl_allows(["role:editor"], viewer)
    assert acl_allows(["role:editor"], editor)
    assert acl_allows(["role:editor"], owner)
    assert not acl_allows(["role:owner"], editor)
    assert acl_allows(["role:owner"], owner)
    assert acl_allows(["project:*"], viewer)


def test_named_user_acl() -> None:
    alice, bob = _user(), _user()
    acl = [f"user:{alice.id}"]
    assert acl_allows(acl, effective_principals(_access(Role.viewer, alice)))
    assert not acl_allows(acl, effective_principals(_access(Role.owner, bob)))


def test_agent_without_on_behalf_of_only_sees_project_content() -> None:
    project = _project()
    access = ProjectAccess(project=project, principal=Principal.for_agent(_agent(project)), role=Role.editor)
    principals = effective_principals(access)
    assert principals == {"project:*"}
    assert not acl_allows(["role:viewer"], principals)
    assert not acl_allows(["role:editor"], principals)


def test_agent_on_behalf_of_member_inherits_member_principals() -> None:
    project = _project()
    alice = _user()
    access = ProjectAccess(project=project, principal=Principal.for_agent(_agent(project)), role=Role.editor)
    principals = effective_principals(access, on_behalf_of_user=alice, role=Role.editor)
    assert principals == principals_for_member(alice.id, Role.editor)
    assert acl_allows([f"user:{alice.id}"], principals)
    assert acl_allows(["role:editor"], principals)
    assert not acl_allows(["role:owner"], principals)


def test_on_behalf_of_defaults_to_viewer_role() -> None:
    alice = _user()
    principals = effective_principals(_access(Role.owner), on_behalf_of_user=alice)
    assert "role:editor" not in principals
    assert f"user:{alice.id}" in principals


def test_empty_acl_denies() -> None:
    assert not acl_allows([], {"project:*"})
    assert not acl_allows(None, {"project:*"})


def test_effective_clearance() -> None:
    project = _project()
    assert effective_clearance(_user(3), _agent(project, 2), None) == 2
    assert effective_clearance(_user(1), _agent(project, 3), None) == 1
    assert effective_clearance(_user(3), None, 0) == 0
    assert effective_clearance(None, _agent(project, 2), 3) == 2
    assert effective_clearance(None, None, None) == 0


def test_merge_acls_and_classifications() -> None:
    uid = uuid.uuid4()
    assert merge_acls([["project:*"], ["project:*"]]) == ["project:*"]
    assert merge_acls([["project:*"], ["role:editor"]]) == ["role:editor"]
    assert merge_acls([["role:editor", f"user:{uid}"], [f"user:{uid}"]]) == [f"user:{uid}"]
    assert merge_acls([["role:owner"], [f"user:{uid}"]]) == []
    assert merge_classifications([0, 2, 1]) == 2
    assert merge_classifications([]) == 0


def test_validate_acl_principals() -> None:
    uid = uuid.uuid4()
    assert validate_acl_principals(None) == ["project:*"]
    assert validate_acl_principals([" role:editor ", "role:editor", f"user:{str(uid).upper()}"]) == [
        "role:editor",
        f"user:{uid}",
    ]
    with pytest.raises(ValueError, match="invalide"):
        validate_acl_principals(["group:finance"])
    with pytest.raises(ValueError):
        validate_acl_principals([" "])
    assert parse_acl_csv("role:owner, project:*") == ["role:owner", "project:*"]
    assert parse_acl_csv("  ") is None


def test_acl_terms_filter() -> None:
    assert acl_terms_filter({"role:viewer", "project:*"}) == {
        "terms": {"acl_principals": ["project:*", "role:viewer"]}
    }
