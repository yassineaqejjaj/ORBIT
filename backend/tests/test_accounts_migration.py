"""Account migration tool (ADR 001 §8, NOV-113) on a database filled with synthetic accounts.

What is checked: the inventory is exact, read only and shows no address in clear; the dry-run reconciliation writes
nothing (table fingerprints before / after); ``--apply`` is refused without a fresh backup of this database, an
operator, or a correctly signed approval, and then links the approved pairs only; the password switch is reversible
in one command; there is at most one break-glass account.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.admin import accounts
from app.admin.__main__ import _parser
from app.config import settings
from app.db import get_sessionmaker, utcnow
from app.models import Agent, AuditLog, ExternalIdentity, Project, ProjectMember, User, Workspace
from app.security import hash_password
from tests.conftest import DEFAULT_PASSWORD

pytestmark = pytest.mark.usefixtures("app")  # migrates the test database before anything touches it

ISSUER = "https://idp.migration.test/realms/orion"
KEY = "approval-key-for-tests-0123456789abcdef"


async def cli(argv: list[str]) -> int:
    return await accounts.run_accounts(_parser().parse_args(["accounts", *argv]))


async def fingerprint() -> dict[str, tuple[int, str]]:
    """Count and content hash of every table the tool may touch (or must not)."""
    result: dict[str, tuple[int, str]] = {}
    async with get_sessionmaker()() as session:
        for table in ("users", "external_identities", "audit_log", "agents", "project_members", "projects"):
            row = (
                await session.execute(
                    text(
                        f"SELECT count(*), coalesce(md5(string_agg(md5(to_jsonb(t)::text), ',' "
                        f"ORDER BY md5(to_jsonb(t)::text))), '') FROM {table} t"
                    )
                )
            ).one()
            result[table] = (int(row[0]), str(row[1]))
    return result


class World:
    """Synthetic accounts of two workspaces. Every address carries a per-test token."""

    def __init__(self) -> None:
        self.tag = uuid.uuid4().hex[:8]
        self.ws1, self.ws2 = uuid.uuid4(), uuid.uuid4()
        self.users: dict[str, User] = {}
        self.project_slug = f"mig-{self.tag}"

    def email(self, name: str, domain: str = "acme.test") -> str:
        return f"{name}.{self.tag}@{domain}"

    async def build(self) -> World:
        async with get_sessionmaker()() as session:
            session.add_all(
                [Workspace(id=self.ws1, name="Espace 1"), Workspace(id=self.ws2, name="Espace 2")]
            )
            await session.flush()

            def add(key: str, email: str, **kw: Any) -> None:
                user = User(
                    email=email,
                    full_name=f"Compte {key}",
                    password_hash=hash_password(DEFAULT_PASSWORD),
                    workspace_id=kw.pop("workspace_id", self.ws1),
                    **kw,
                )
                self.users[key] = user
                session.add(user)

            add("clean", self.email("clean"), clearance=2, last_login_at=utcnow() - timedelta(days=3))
            add("admin", self.email("admin"), is_admin=True, clearance=3)
            add("dup_a", self.email("dup"))
            add("dup_b", f"dup.{self.tag}+x@acme.test")
            add("other_ws", self.email("other"), workspace_id=self.ws2)
            add("unverifiable", f"x.{self.tag}@corp.local")
            add("malformed", f"not-an-address-{self.tag}")
            add("linked", self.email("linked"))
            add("two", self.email("two"))
            await session.flush()
            project = Project(slug=self.project_slug, name="Projet migration", workspace_id=self.ws1)
            session.add(project)
            await session.flush()
            session.add(ProjectMember(project_id=project.id, user_id=self.users["clean"].id, role="owner"))
            session.add(ProjectMember(project_id=project.id, user_id=self.users["admin"].id, role="viewer"))
            session.add(
                Agent(
                    project_id=project.id,
                    workspace_id=self.ws1,
                    name="Agent synthétique",
                    kind="engineering",
                    clearance=2,
                    api_key_prefix=self.tag,
                    api_key_hash="argon2-synthetic",
                )
            )
            session.add(
                ExternalIdentity(
                    user_id=self.users["linked"].id,
                    workspace_id=self.ws1,
                    issuer=ISSUER,
                    subject=f"sub-linked-{self.tag}",
                    linked_by="confirmed",
                )
            )
            await session.commit()
        return self

    def export(self, tmp_path: Path) -> Path:
        t = self.tag
        subjects = [
            {
                "sub": f"s-clean-{t}",
                "email": self.email("clean"),
                "email_verified": True,
                "workspace_id": str(self.ws1),
            },
            {"sub": f"s-unverified-{t}", "email": self.email("admin"), "email_verified": False},
            {"sub": f"s-noemail-{t}"},
            {"sub": f"s-domain-{t}", "email": self.email("two", "intrus.test"), "email_verified": True},
            {"sub": f"s-dup-{t}", "email": self.email("dup"), "email_verified": True},
            {
                "sub": f"s-ws-{t}",
                "email": self.email("other"),
                "email_verified": True,
                "workspace_id": str(self.ws1),
            },
            {"sub": f"s-nolocal-{t}", "email": self.email("ghost"), "email_verified": True},
            {"sub": f"sub-linked-{t}", "email": self.email("two"), "email_verified": True},
            {"sub": f"s-two-a-{t}", "email": self.email("two"), "email_verified": True},
            {"sub": f"s-two-b-{t}", "email": self.email("two"), "email_verified": True},
            {"sub": f"s-twice-{t}", "email": self.email("ghost"), "email_verified": True},
            {"sub": f"s-twice-{t}", "email": self.email("ghost"), "email_verified": True},
        ]
        path = tmp_path / "idp-export.json"
        path.write_text(json.dumps({"issuer": ISSUER, "subjects": subjects}), encoding="utf-8")
        return path

    def sub(self, name: str) -> str:
        return f"{name}-{self.tag}"


@pytest.fixture
async def world() -> World:
    return await World().build()


@pytest.fixture
def tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Approval key and a backup directory; returns the backup directory."""
    backups = tmp_path / "backups"
    backups.mkdir()
    monkeypatch.setattr(settings, "accounts_approval_key", KEY)
    monkeypatch.setattr(settings, "accounts_backup_dir", str(backups))
    return backups


def write_backup(
    directory: Path, backup_id: str, *, database: str | None = None, age_hours: float = 1.0
) -> None:
    (directory / f"{backup_id}.json").write_text(
        json.dumps(
            {
                "id": backup_id,
                "database": database or make_url(settings.database_url).database,
                "created_at": (utcnow() - timedelta(hours=age_hours)).isoformat(),
            }
        ),
        encoding="utf-8",
    )


def by_sub(proposals: dict[str, Any], sub: str) -> dict[str, Any]:
    return next(p for p in proposals["proposals"] if p["sub"] == sub)


# --- Inventory ----------------------------------------------------------------------------------------------------


async def test_the_inventory_is_exact_and_shows_no_address(tmp_path: Path, capsys: Any) -> None:
    async with get_sessionmaker()() as session:
        before = await accounts.build_inventory(session)
    w = await World().build()  # the deltas below are exactly this world
    assert await cli(["inventory", "--out", str(tmp_path / "inv.json")]) == 0
    inventory = json.loads((tmp_path / "inv.json").read_text())
    serial = json.dumps(inventory)
    users = {r["email_hash"]: r for r in inventory["users"]}

    def row(world_: World, key: str) -> dict[str, Any]:
        return users[accounts.email_hash(world_.users[key].email)]

    clean = row(w, "clean")
    assert (clean["clearance"], clean["platform_admin"], clean["project_roles"]) == (2, False, {"owner": 1})
    assert clean["last_login_at"] and clean["sso_identities"] == 0 and clean["workspace_id"] == str(w.ws1)
    assert row(w, "admin")["platform_admin"] is True and row(w, "admin")["project_roles"] == {"viewer": 1}
    assert row(w, "linked")["sso_identities"] == 1
    assert row(w, "other_ws")["workspace_id"] == str(w.ws2)
    assert row(w, "unverifiable")["email_unverifiable"] == "reserved_or_internal_domain"
    assert row(w, "malformed")["email_unverifiable"] == "malformed"
    assert row(w, "clean")["email_unverifiable"] == "reserved_or_internal_domain"  # ``.test`` is reserved too
    groups = [g for g in inventory["duplicates"] if str(w.users["dup_a"].id) in g["user_ids"]]
    assert len(groups) == 1 and set(groups[0]["user_ids"]) == {
        str(w.users["dup_a"].id),
        str(w.users["dup_b"].id),
    }
    keys = [k for k in inventory["service_keys"] if k["project"] == w.project_slug]
    assert len(keys) == 1 and keys[0]["clearance"] == 2 and keys[0]["active"] is True
    assert keys[0]["key"].startswith("orb_") and keys[0]["key"].endswith("••••")
    # exact deltas against the inventory taken before this world existed
    summary, base = inventory["summary"], before["summary"]
    assert summary["users"] - base["users"] == 9
    assert summary["platform_admins"] - base["platform_admins"] == 1
    assert summary["with_sso_identity"] - base["with_sso_identity"] == 1
    assert summary["service_keys"] - base["service_keys"] == 1
    assert summary["duplicate_groups"] - base["duplicate_groups"] == 1
    assert (
        summary["unverifiable_emails"] - base["unverifiable_emails"] == 9
    )  # every `.test` / `.local` / malformed
    # nothing in clear: no address, no password hash, no secret
    for user in w.users.values():
        assert user.email not in serial and user.password_hash not in serial
    assert "argon2" not in serial and "$argon2" not in serial
    csv_text = accounts.inventory_csv(inventory)
    assert (
        csv_text.splitlines()[0].startswith("user_id,email_hash") and w.users["clean"].email not in csv_text
    )
    masked = await _masked()
    assert "c***@acme.test" in masked and w.users["clean"].email not in masked
    capsys.readouterr()


async def _masked() -> str:
    async with get_sessionmaker()() as session:
        return json.dumps(await accounts.build_inventory(session, emails="masked"))


async def test_the_inventory_transaction_refuses_any_write(world: World) -> None:
    async with get_sessionmaker()() as session:
        await accounts.build_inventory(session)
        with pytest.raises(DBAPIError, match="read-only"):
            await session.execute(text("UPDATE users SET clearance = 0"))
        await session.rollback()
    assert (await fingerprint())["users"][0] >= len(world.users)


# --- Reconciliation: dry-run --------------------------------------------------------------------------------------


async def test_the_dry_run_proposes_links_lists_every_conflict_and_writes_nothing(
    world: World, tmp_path: Path, tool: Path
) -> None:
    export = world.export(tmp_path)
    before = await fingerprint()
    out = tmp_path / "proposal.json"
    code = await cli(
        ["reconcile", "--idp-export", str(export), "--allowed-domain", "acme.test", "--out", str(out)]
    )
    assert code == 0 and await fingerprint() == before  # not one row, not one audit entry
    proposals = json.loads(out.read_text())
    assert proposals["mode"] == "dry-run" and proposals["issuer"] == ISSUER

    clean = by_sub(proposals, world.sub("s-clean"))
    assert clean["status"] == "proposed" and clean["conflicts"] == []
    assert clean["user_id"] == str(world.users["clean"].id) and "email" not in clean
    conflicts = {
        "s-unverified": "email_unverified",
        "s-noemail": "email_absent",
        "s-domain": "unexpected_domain",
        "s-dup": "two_accounts_for_subject",
        "s-ws": "workspace_mismatch",
        "s-nolocal": "no_local_account",
        "sub-linked": "subject_linked_to_another_account",
        "s-two-a": "two_subjects_for_account",
        "s-twice": "duplicate_subject_in_export",
    }
    for sub, conflict in conflicts.items():
        proposal = by_sub(proposals, world.sub(sub))
        assert proposal["status"] == "conflict" and conflict in proposal["conflicts"], (sub, proposal)
    assert by_sub(proposals, world.sub("s-two-b"))["status"] == "conflict"
    assert json.dumps(proposals).count(world.users["clean"].email) == 0  # hashes only


# --- Reconciliation: apply ----------------------------------------------------------------------------------------


async def approved(world: World, tmp_path: Path, accept: list[str] | None = None) -> tuple[Path, Path]:
    export = world.export(tmp_path)
    proposal = tmp_path / "proposal.json"
    assert await cli(["reconcile", "--idp-export", str(export), "--out", str(proposal)]) == 0
    chosen = accept or [by_sub(json.loads(proposal.read_text()), world.sub("s-clean"))["proposal_id"]]
    approval = tmp_path / "approval.json"
    argv = ["approve", "--proposal", str(proposal), "--approver", "dpo@acme.test", "--out", str(approval)]
    for pid in chosen:
        argv += ["--accept", pid]
    assert await cli(argv) == 0
    return export, approval


def apply_args(
    export: Path, approval: Path | None, backup: str | None, operator: str | None = "ops"
) -> list[str]:
    argv = ["reconcile", "--idp-export", str(export), "--apply"]
    if approval is not None:
        argv += ["--approval", str(approval)]
    if backup is not None:
        argv += ["--confirm-backup", backup]
    if operator is not None:
        argv += ["--operator", operator]
    return argv


async def test_apply_is_refused_without_backup_operator_or_a_valid_approval(
    world: World, tmp_path: Path, tool: Path, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    export, approval = await approved(world, tmp_path)
    write_backup(tool, "ok-backup")
    write_backup(tool, "other-db", database="une_autre_base")
    write_backup(tool, "stale", age_hours=48)
    before = await fingerprint()

    refusals = [
        apply_args(export, approval, None),  # no backup id
        apply_args(export, approval, "inexistante"),  # no such manifest
        apply_args(export, approval, "other-db"),  # a backup of another database
        apply_args(export, approval, "stale"),  # older than the allowed age
        apply_args(export, approval, "../etc/passwd"),  # not an identifier
        apply_args(export, approval, "ok-backup", operator=None),  # no operator for the audit
        apply_args(export, None, "ok-backup"),  # no approval file
    ]
    for argv in refusals:
        assert await cli(argv) == 2, argv
        assert await fingerprint() == before, argv  # a refusal never leaves a trace in the base

    tampered = tmp_path / "tampered.json"
    data = json.loads(approval.read_text())
    data["items"][0]["sub"] = world.sub("s-nolocal")  # a pair nobody approved
    tampered.write_text(json.dumps(data))
    assert await cli(apply_args(export, tampered, "ok-backup")) == 2
    wrong_issuer = tmp_path / "wrong-issuer.json"
    other = {k: v for k, v in json.loads(approval.read_text()).items() if k != "signature"}
    other["issuer"] = "https://autre.test"
    wrong_issuer.write_text(json.dumps({**other, "signature": accounts.sign(other, KEY)}))
    assert await cli(apply_args(export, wrong_issuer, "ok-backup")) == 2
    monkeypatch.setattr(settings, "accounts_approval_key", "")  # no key: nothing can be verified
    assert await cli(apply_args(export, approval, "ok-backup")) == 2
    monkeypatch.setattr(settings, "accounts_backup_dir", "")
    assert await cli(apply_args(export, approval, "ok-backup")) == 2
    assert await fingerprint() == before
    assert "Refusé" in capsys.readouterr().err


async def test_apply_links_only_the_approved_pairs_then_the_proposal_is_settled(
    world: World, tmp_path: Path, tool: Path
) -> None:
    export, approval = await approved(world, tmp_path)
    write_backup(tool, "backup-1")
    before = await fingerprint()
    assert await cli(apply_args(export, approval, "backup-1", operator="Opérateur Un")) == 0
    after = await fingerprint()
    assert after["external_identities"][0] == before["external_identities"][0] + 1
    assert after["users"] == before["users"] and after["agents"] == before["agents"]  # nothing else touched
    async with get_sessionmaker()() as session:
        rows = list(
            await session.scalars(
                select(ExternalIdentity).where(
                    ExternalIdentity.user_id == world.users["clean"].id, ExternalIdentity.issuer == ISSUER
                )
            )
        )
        assert [(r.subject, r.linked_by, r.email) for r in rows] == [
            (world.sub("s-clean"), "admin_approved", None)
        ]
        entry = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "account.link", AuditLog.target_id == str(world.users["clean"].id)
            )
        )
    assert entry is not None and entry.details["operator"] == "Opérateur Un"
    again = tmp_path / "again.json"
    assert await cli(["reconcile", "--idp-export", str(export), "--out", str(again)]) == 0
    assert by_sub(json.loads(again.read_text()), world.sub("s-clean"))["status"] == "already_linked"


async def test_an_approval_that_became_a_conflict_aborts_everything(
    world: World, tmp_path: Path, tool: Path
) -> None:
    export = world.export(tmp_path)
    proposal = tmp_path / "proposal.json"
    await cli(["reconcile", "--idp-export", str(export), "--out", str(proposal)])
    data = json.loads(proposal.read_text())
    clean = by_sub(data, world.sub("s-clean"))
    # a signed approval that smuggles a conflicting pair next to a good one (signed by someone holding the key)
    conflict = by_sub(data, world.sub("s-dup"))
    payload = {
        "issuer": ISSUER,
        "approver": "x",
        "approved_at": utcnow().isoformat(),
        "items": [
            {"proposal_id": clean["proposal_id"], "user_id": clean["user_id"], "sub": clean["sub"]},
            {"proposal_id": conflict["proposal_id"], "user_id": conflict["user_id"], "sub": conflict["sub"]},
        ],
    }
    approval = tmp_path / "forged.json"
    approval.write_text(json.dumps({**payload, "signature": accounts.sign(payload, KEY)}))
    write_backup(tool, "backup-2")
    before = await fingerprint()
    assert await cli(apply_args(export, approval, "backup-2")) == 2
    assert await fingerprint() == before  # the good pair was not linked either: all or none
    # and `approve` itself refuses a proposal that is not "proposed"
    assert (
        await cli(
            [
                "approve",
                "--proposal",
                str(proposal),
                "--accept",
                conflict["proposal_id"],
                "--approver",
                "x",
                "--out",
                str(tmp_path / "n.json"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "n.json").exists()


# --- Flags, rollback, break-glass ---------------------------------------------------------------------------------


async def login(client: httpx.AsyncClient, email: str) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})


async def test_the_password_switch_is_guarded_audited_and_reversible_in_one_command(
    world: World, tmp_path: Path, tool: Path, client: httpx.AsyncClient
) -> None:
    clean, linked = world.users["clean"].email, world.users["linked"].email
    write_backup(tool, "backup-3")
    assert (await login(client, clean)).status_code == 200  # default: password works

    # no identity: refused (it would lock the account out); no --apply: nothing changes
    assert (
        await cli(
            [
                "disable-password",
                "--user",
                clean,
                "--apply",
                "--confirm-backup",
                "backup-3",
                "--operator",
                "ops",
            ]
        )
        == 2
    )
    before = await fingerprint()
    assert await cli(["disable-password", "--user", linked]) == 0 and await fingerprint() == before  # dry-run
    assert await cli(["disable-password", "--user", linked, "--apply", "--operator", "ops"]) == 2  # no backup
    assert await fingerprint() == before

    assert (
        await cli(
            [
                "disable-password",
                "--user",
                linked,
                "--apply",
                "--confirm-backup",
                "backup-3",
                "--operator",
                "ops",
            ]
        )
        == 0
    )
    refused = await login(client, linked)
    assert refused.status_code == 403 and "SSO" in refused.json()["detail"]
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": linked, "password": "mauvais-mot-de-passe"}
    )
    assert wrong.status_code == 401  # a wrong password still reveals nothing about the account
    async with get_sessionmaker()() as session:
        entry = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "account.flags", AuditLog.target_id == str(world.users["linked"].id)
            )
        )
    assert (
        entry is not None
        and entry.details["password_login_disabled"] is True
        and entry.details["operator"] == "ops"
    )

    assert (
        await cli(["enable-password", "--user", linked, "--apply", "--operator", "ops"]) == 0
    )  # one command, no backup
    assert (await login(client, linked)).status_code == 200


async def test_there_is_at_most_one_break_glass_account_and_it_stays_on_passwords(
    world: World, tmp_path: Path, tool: Path, client: httpx.AsyncClient
) -> None:
    admin, plain = world.users["admin"].email, world.users["clean"].email
    async with get_sessionmaker()() as session:  # another test's break-glass account must not leak in here
        await session.execute(text("UPDATE users SET is_break_glass = false"))
        await session.commit()
    assert (
        await cli(["break-glass", "--user", plain, "--apply", "--operator", "ops"]) == 2
    )  # not an administrator
    assert await cli(["break-glass", "--user", admin, "--apply", "--operator", "ops"]) == 0
    async with get_sessionmaker()() as session:
        other = User(
            email=f"admin2.{world.tag}@acme.test",
            full_name="Second admin",
            password_hash=hash_password(DEFAULT_PASSWORD),
            is_admin=True,
            workspace_id=world.ws1,
        )
        session.add(other)
        await session.commit()
    assert await cli(["break-glass", "--user", other.email, "--apply", "--operator", "ops"]) == 2  # only one
    # the break-glass account is never pushed out of the password, even if flags were set by hand
    async with get_sessionmaker()() as session:
        with pytest.raises(DBAPIError):  # the database refuses the combination
            await session.execute(text("UPDATE users SET sso_required = true WHERE email = :e"), {"e": admin})
            await session.commit()
        await session.rollback()
    assert (
        await cli(
            ["disable-password", "--user", admin, "--apply", "--confirm-backup", "x", "--operator", "ops"]
        )
        == 2
    )
    assert (await login(client, admin)).status_code == 200
    assert await cli(["break-glass", "--user", admin, "--unset", "--apply", "--operator", "ops"]) == 0
    assert (
        await cli(["break-glass", "--user", admin, "--unset", "--apply", "--operator", "ops"]) == 2
    )  # not flagged


def test_the_helpers_hash_mask_and_normalize() -> None:
    assert accounts.normalize_email("Jean.Dupont+tag@Acme.TEST") == "jean.dupont@acme.test"
    assert accounts.mask_email("jean@acme.test") == "j***@acme.test"
    assert (
        accounts.email_hash("A@b.test") == accounts.email_hash("a@B.test")
        and len(accounts.email_hash("a@b.test")) == 16
    )
    assert accounts.unverifiable_reason("a@b.com") is None
    assert accounts.unverifiable_reason("a@intranet") == "no_top_level_domain"
    assert accounts.unverifiable_reason("a@corp.local") == "reserved_or_internal_domain"
    assert accounts.unverifiable_reason("pas-une-adresse") == "malformed"
