"""Account migration tool (ADR 001 §8, NOV-113): ``python -m app.admin accounts <command>``.

The tool only prepares and records the move to SSO; the application never runs it and **nothing is
executed in production by this ticket**. Every command is read-only unless it carries ``--apply``.

* ``inventory`` (phase 0): read-only (the transaction is ``READ ONLY``). Accounts, service keys,
  duplicates and addresses an IdP cannot verify. E-mails are **hashed** by default
  (``--emails masked`` shows ``a***@domain``); no option prints an address in clear, and no secret or
  password hash is ever read.
* ``reconcile`` (phase 2): matches an IdP export to local accounts and **proposes** links; conflicts
  are listed (two accounts for one subject, a subject already linked elsewhere, missing or
  unverified e-mail, unexpected domain, workspace mismatch...). Without ``--apply`` it writes nothing.
  With ``--apply`` it needs ``--confirm-backup <id>`` (a fresh manifest of the current database) and
  ``--approval <file>`` (signed by ``approve``): it links **only** the approved pairs, all or none.
* ``approve``: signs (HMAC, ``ORBIT_ACCOUNTS_APPROVAL_KEY``) the proposals a human accepted; it
  writes a file only.
* ``disable-password`` / ``enable-password`` (phase 3 and its rollback), ``break-glass`` (the one
  administrator account kept outside SSO).

Each link and flag change is audited (``account.link`` / ``account.flags``) with the operator's name.
Restoration procedure: ``docs/ACCOUNTS_MIGRATION.md``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import io
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.models import Agent, ExternalIdentity, Project, ProjectMember, User
from app.security import mask_api_key
from app.services import audit

EXIT_OK, EXIT_USAGE = 0, 2
#: Top-level domains / domains an IdP cannot verify mail for (reserved, internal or placeholder).
UNVERIFIABLE_TLDS = frozenset({"test", "invalid", "local", "localhost", "example", "internal", "lan"})
UNVERIFIABLE_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


class Refused(Exception):
    """A precondition failed: nothing was written."""


# --- E-mail helpers --------------------------------------------------------


def normalize_email(email: str) -> str:
    """Lower case, ``+tag`` removed: two accounts with the same normalized address are duplicates."""
    local, _, domain = email.strip().lower().partition("@")
    return f"{local.split('+', 1)[0]}@{domain}"


def email_hash(email: str) -> str:
    material = f"{settings.accounts_export_salt}|{email.strip().lower()}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def unverifiable_reason(email: str) -> str | None:
    if not _EMAIL.match(email):
        return "malformed"
    domain = email.rsplit("@", 1)[1].lower()
    if "." not in domain:
        return "no_top_level_domain"
    if domain in UNVERIFIABLE_DOMAINS or domain.rsplit(".", 1)[1] in UNVERIFIABLE_TLDS:
        return "reserved_or_internal_domain"
    return None


def _display(email: str, mode: str) -> dict[str, str]:
    return {"email_hash": email_hash(email)} if mode == "hash" else {"email_masked": mask_email(email)}


# --- Inventory (read only) -------------------------------------------------


async def build_inventory(session: AsyncSession, *, emails: str = "hash") -> dict[str, Any]:
    await session.execute(text("SET TRANSACTION READ ONLY"))  # the database itself refuses any write
    users = list(await session.scalars(select(User).order_by(User.workspace_id, User.created_at, User.id)))
    roles: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    for user_id, role, count in (
        await session.execute(
            select(ProjectMember.user_id, ProjectMember.role, func.count()).group_by(
                ProjectMember.user_id, ProjectMember.role
            )
        )
    ).tuples():
        roles[user_id][str(role)] = int(count)
    identities: Counter[uuid.UUID] = Counter(
        {
            u: int(n)
            for u, n in (
                await session.execute(
                    select(ExternalIdentity.user_id, func.count()).group_by(ExternalIdentity.user_id)
                )
            ).tuples()
        }
    )
    rows: list[dict[str, Any]] = []
    groups: dict[str, list[User]] = defaultdict(list)
    unverifiable: list[dict[str, Any]] = []
    for user in users:
        groups[normalize_email(user.email)].append(user)
        reason = unverifiable_reason(user.email)
        if reason:
            unverifiable.append({"user_id": str(user.id), "reason": reason, **_display(user.email, emails)})
        rows.append(
            {
                "user_id": str(user.id),
                **_display(user.email, emails),
                "domain": user.email.rsplit("@", 1)[-1].lower() if "@" in user.email else None,
                "workspace_id": str(user.workspace_id),
                "platform_admin": bool(user.is_admin),
                "project_roles": dict(sorted(roles[user.id].items())),
                "clearance": int(user.clearance),
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "created_at": user.created_at.isoformat(),
                "sso_identities": identities[user.id],
                "password_login_disabled": bool(user.password_login_disabled),
                "sso_required": bool(user.sso_required),
                "break_glass": bool(user.is_break_glass),
                "email_unverifiable": reason,
            }
        )
    duplicates = [
        {
            "email_hash": email_hash(key),
            "user_ids": [str(u.id) for u in members],
            "workspaces": sorted({str(u.workspace_id) for u in members}),
        }
        for key, members in sorted(groups.items())
        if len(members) > 1
    ]
    keys = [
        {
            "key": mask_api_key(agent.api_key_prefix),
            "name": agent.name,
            "project": slug,
            "workspace_id": str(agent.workspace_id),
            "role": agent.role,
            "clearance": int(agent.clearance),
            "active": bool(agent.active),
            "expires_at": agent.expires_at.isoformat() if agent.expires_at else None,
            "last_used_at": agent.last_used_at.isoformat() if agent.last_used_at else None,
        }
        for agent, slug in (
            await session.execute(
                select(Agent, Project.slug)
                .join(Project, Project.id == Agent.project_id)
                .order_by(Agent.workspace_id, Project.slug, Agent.created_at)
            )
        ).tuples()
    ]
    return {
        "generated_at": utcnow().isoformat(),
        "emails": emails,
        "summary": {
            "users": len(rows),
            "platform_admins": sum(r["platform_admin"] for r in rows),
            "with_sso_identity": sum(1 for r in rows if r["sso_identities"]),
            "never_logged_in": sum(1 for r in rows if r["last_login_at"] is None),
            "duplicate_groups": len(duplicates),
            "unverifiable_emails": len(unverifiable),
            "service_keys": len(keys),
            "active_service_keys": sum(1 for k in keys if k["active"]),
            "break_glass": sum(r["break_glass"] for r in rows),
        },
        "users": rows,
        "service_keys": keys,
        "duplicates": duplicates,
        "unverifiable_emails": unverifiable,
    }


def inventory_csv(inventory: dict[str, Any]) -> str:
    rows = inventory["users"]
    out = io.StringIO()
    if rows:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, dict) else v for k, v in row.items()})
    return out.getvalue()


# --- Reconciliation (dry-run proposals) ------------------------------------


def proposal_id(user_id: uuid.UUID | str, issuer: str, sub: str) -> str:
    return hashlib.sha256(f"{user_id}|{issuer}|{sub}".encode()).hexdigest()[:16]


def load_export(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        issuer, subjects = str(data["issuer"]), list(data["subjects"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refused(
            f"Export de l'IdP illisible ({type(exc).__name__}) : attendu {{issuer, subjects[]}}"
        ) from exc
    if not issuer or not all(isinstance(s, dict) and s.get("sub") for s in subjects):
        raise Refused("Export de l'IdP invalide : chaque sujet doit porter `sub`")
    return issuer, subjects


async def build_proposals(
    session: AsyncSession,
    issuer: str,
    subjects: Sequence[dict[str, Any]],
    *,
    allowed_domains: Sequence[str] = (),
) -> dict[str, Any]:
    """Match each IdP subject to local accounts. Pure reading: never writes."""
    users = list(await session.scalars(select(User)))
    by_exact: dict[str, list[User]] = defaultdict(list)
    by_normal: dict[str, list[User]] = defaultdict(list)
    for account in users:
        by_exact[account.email.lower()].append(account)
        by_normal[normalize_email(account.email)].append(account)
    linked = list(await session.scalars(select(ExternalIdentity).where(ExternalIdentity.issuer == issuer)))
    sub_owner = {i.subject: i.user_id for i in linked}
    user_sub = {i.user_id: i.subject for i in linked}
    sub_counts = Counter(str(s["sub"]) for s in subjects)
    allowed = {d.lower() for d in allowed_domains}

    proposals: list[dict[str, Any]] = []
    for subject in subjects:
        sub, email = str(subject["sub"]), str(subject.get("email") or "")
        conflicts: list[str] = []
        user: User | None = None
        if sub_counts[sub] > 1:
            conflicts.append("duplicate_subject_in_export")
        if not email:
            conflicts.append("email_absent")
        else:
            if subject.get("email_verified") is not True:
                conflicts.append("email_unverified")
            if allowed and email.rsplit("@", 1)[-1].lower() not in allowed:
                conflicts.append("unexpected_domain")
            exact = by_exact.get(email.lower(), [])
            similar = by_normal.get(normalize_email(email), [])
            if len(similar) > 1:
                conflicts.append("two_accounts_for_subject")
            if len(exact) == 1:
                user = exact[0]
            elif not exact and len(similar) == 1:
                conflicts.append("only_similar_address")  # same address up to +tag/case: a human decides
            if user is None and not similar:
                conflicts.append("no_local_account")
        status = "proposed"
        if user is not None:
            expected = subject.get("workspace_id")
            if expected and str(expected).lower() != str(user.workspace_id):
                conflicts.append("workspace_mismatch")
            if sub_owner.get(sub) == user.id:
                status = "already_linked"
            elif sub in sub_owner:
                conflicts.append("subject_linked_to_another_account")
            if user.id in user_sub and user_sub[user.id] != sub:
                conflicts.append("account_linked_to_another_subject")
        if conflicts:
            status = "conflict"
        proposals.append(
            {
                "proposal_id": proposal_id(user.id, issuer, sub)
                if user
                else proposal_id("none", issuer, sub),
                "status": status,
                "sub": sub,
                "user_id": str(user.id) if user else None,
                "workspace_id": str(user.workspace_id) if user else None,
                **(_display(email, "hash") if email else {}),
                "conflicts": sorted(set(conflicts)),
            }
        )
    per_user = Counter(p["user_id"] for p in proposals if p["user_id"] and p["status"] != "already_linked")
    for p in proposals:
        if p["user_id"] and per_user[p["user_id"]] > 1 and "two_subjects_for_account" not in p["conflicts"]:
            p["conflicts"] = sorted({*p["conflicts"], "two_subjects_for_account"})
            p["status"] = "conflict"
    return {
        "issuer": issuer,
        "generated_at": utcnow().isoformat(),
        "mode": "dry-run",
        "summary": dict(Counter(p["status"] for p in proposals)),
        "proposals": proposals,
    }


# --- Signed approval -------------------------------------------------------


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(payload: dict[str, Any], key: str) -> str:
    return hmac.new(key.encode(), _canonical(payload), hashlib.sha256).hexdigest()


def make_approval(
    proposals: dict[str, Any], accept: Sequence[str], approver: str, key: str
) -> dict[str, Any]:
    by_id = {p["proposal_id"]: p for p in proposals["proposals"]}
    items = []
    for pid in accept:
        proposal = by_id.get(pid)
        if proposal is None:
            raise Refused(f"Proposition inconnue : {pid}")
        if proposal["status"] != "proposed":
            raise Refused(
                f"La proposition {pid} est « {proposal['status']} » : elle ne peut pas être approuvée"
            )
        items.append({"proposal_id": pid, "user_id": proposal["user_id"], "sub": proposal["sub"]})
    payload = {
        "issuer": proposals["issuer"],
        "approver": approver,
        "approved_at": utcnow().isoformat(),
        "items": items,
    }
    return {**payload, "signature": sign(payload, key)}


def read_approval(path: Path, key: str, issuer: str) -> dict[str, Any]:
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
        signature = str(approval.pop("signature"))
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        raise Refused("Fichier d'approbation illisible ou non signé") from exc
    if not key or not hmac.compare_digest(signature, sign(approval, key)):
        raise Refused("Signature du fichier d'approbation invalide")
    if approval.get("issuer") != issuer:
        raise Refused("Le fichier d'approbation concerne un autre émetteur")
    if not approval.get("items"):
        raise Refused("Le fichier d'approbation ne contient aucune liaison")
    return approval


# --- Backup confirmation ---------------------------------------------------


def check_backup(backup_id: str | None, *, now: datetime | None = None) -> None:
    """``--confirm-backup <id>`` names a fresh manifest of *this* database in the backup directory."""
    if not backup_id:
        raise Refused("Écriture refusée : --confirm-backup <identifiant de sauvegarde> est obligatoire")
    if not settings.accounts_backup_dir or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", backup_id):
        raise Refused("Sauvegarde non vérifiable (ORBIT_ACCOUNTS_BACKUP_DIR absent ou identifiant invalide)")
    manifest = Path(settings.accounts_backup_dir) / f"{backup_id}.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(str(data["created_at"]))
        database = str(data["database"])
        declared = str(data["id"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refused(f"Sauvegarde « {backup_id} » introuvable ou manifeste illisible") from exc
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    current = make_url(settings.database_url).database
    if declared != backup_id or database != current:
        raise Refused(f"La sauvegarde « {backup_id} » ne concerne pas la base courante")
    if (now or utcnow()) - created > timedelta(hours=settings.accounts_backup_max_age_hours):
        raise Refused(
            f"La sauvegarde « {backup_id} » date de plus de {settings.accounts_backup_max_age_hours} h"
        )


# --- Writes ----------------------------------------------------------------


async def apply_links(
    session: AsyncSession, approval: dict[str, Any], proposals: dict[str, Any], *, operator: str
) -> list[dict[str, Any]]:
    """Link exactly the approved pairs. All or nothing: a stale item aborts before any write."""
    by_id = {p["proposal_id"]: p for p in proposals["proposals"]}
    plan = []
    for item in approval["items"]:
        proposal = by_id.get(item["proposal_id"])
        if (
            proposal is None
            or proposal["status"] != "proposed"
            or proposal["user_id"] != item["user_id"]
            or proposal["sub"] != item["sub"]
        ):
            raise Refused(
                f"La proposition {item['proposal_id']} n'est plus applicable : relancez le rapprochement"
            )
        plan.append(proposal)
    done = []
    for proposal in plan:
        user = await session.get(User, uuid.UUID(proposal["user_id"]))
        assert user is not None
        session.add(
            ExternalIdentity(
                user_id=user.id,
                workspace_id=user.workspace_id,
                issuer=proposals["issuer"],
                subject=proposal["sub"],
                email=None,  # the e-mail stays out of the link row: only the account and the subject are tied
                linked_by="admin_approved",
            )
        )
        await audit.record(
            session,
            None,
            audit.Actor.system(),
            audit.AuditAction.account_link,
            "user",
            user.id,
            summary="Liaison SSO approuvée appliquée par l'outil de migration",
            details={
                "operator": operator,
                "issuer": proposals["issuer"],
                "proposal_id": proposal["proposal_id"],
            },
        )
        done.append({"proposal_id": proposal["proposal_id"], "user_id": proposal["user_id"]})
    await session.commit()
    return done


async def _user_by_email(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise Refused("Compte introuvable")
    return user


async def _flag_audit(session: AsyncSession, user: User, operator: str, change: dict[str, Any]) -> None:
    await audit.record(
        session,
        None,
        audit.Actor.system(),
        audit.AuditAction.account_flags,
        "user",
        user.id,
        summary="Drapeaux de migration du compte modifiés",
        details={"operator": operator, **change},
    )


async def set_password_login(
    session: AsyncSession, email: str, *, disable: bool, apply: bool, operator: str
) -> dict[str, Any]:
    """Phase 3 (``disable``) or its rollback. Disabling needs a linked identity: nobody is locked out."""
    user = await _user_by_email(session, email)
    if disable:
        if user.is_break_glass:
            raise Refused("Le compte break-glass reste connecté par mot de passe")
        linked = await session.scalar(
            select(func.count()).select_from(ExternalIdentity).where(ExternalIdentity.user_id == user.id)
        )
        if not linked:
            raise Refused("Aucune identité SSO liée : désactiver le mot de passe verrouillerait le compte")
    change = {"password_login_disabled": disable, "sso_required": disable}
    result = {"user_id": str(user.id), "email_hash": email_hash(user.email), **change, "applied": apply}
    if apply:
        user.password_login_disabled, user.sso_required = disable, disable
        await _flag_audit(session, user, operator, change)
        await session.commit()
    return result


async def set_break_glass(
    session: AsyncSession, email: str, *, enable: bool, apply: bool, operator: str
) -> dict[str, Any]:
    user = await _user_by_email(session, email)
    if enable:
        if not user.is_admin:
            raise Refused("Le compte break-glass doit être administrateur de la plateforme")
        existing = await session.scalar(select(User).where(User.is_break_glass.is_(True), User.id != user.id))
        if existing is not None:
            raise Refused("Un compte break-glass existe déjà : retirez-le d'abord")
    elif not user.is_break_glass:
        raise Refused("Ce compte n'est pas le compte break-glass")
    result = {
        "user_id": str(user.id),
        "email_hash": email_hash(user.email),
        "break_glass": enable,
        "applied": apply,
    }
    if apply:
        user.is_break_glass = enable
        if enable:  # outside SSO by definition
            user.password_login_disabled = user.sso_required = False
        await _flag_audit(session, user, operator, {"break_glass": enable})
        await session.commit()
    return result


# --- CLI -------------------------------------------------------------------


def add_parsers(sub: Any) -> None:
    accounts = sub.add_parser(
        "accounts", help="Migration des comptes vers le SSO (inventaire, rapprochement, drapeaux)"
    )
    commands = accounts.add_subparsers(dest="accounts_command", required=True)

    inv = commands.add_parser("inventory", help="Inventaire en lecture seule (e-mails hachés par défaut)")
    inv.add_argument("--emails", choices=("hash", "masked"), default="hash")
    inv.add_argument("--format", choices=("json", "csv"), default="json")
    inv.add_argument("--out", default=None, help="Fichier de sortie (défaut : sortie standard)")

    rec = commands.add_parser(
        "reconcile", help="Rapprochement compte local / sujet de l'IdP (dry-run sans --apply)"
    )
    rec.add_argument(
        "--idp-export",
        required=True,
        help="Export JSON {issuer, subjects:[{sub,email,email_verified,workspace_id}]}",
    )
    rec.add_argument("--allowed-domain", action="append", default=[], help="Domaine attendu (répétable)")
    rec.add_argument("--out", default=None, help="Écrire la proposition dans ce fichier")
    rec.add_argument(
        "--apply",
        action="store_true",
        help="Lier les paires approuvées (exige --approval et --confirm-backup)",
    )
    rec.add_argument("--approval", default=None, help="Fichier d'approbation signé (voir `approve`)")
    rec.add_argument("--confirm-backup", default=None, help="Identifiant de la sauvegarde de la base")
    rec.add_argument("--operator", default=None, help="Nom de l'opérateur (audit)")

    app = commands.add_parser(
        "approve", help="Signer l'approbation de propositions (écrit un fichier, pas la base)"
    )
    app.add_argument("--proposal", required=True, help="Fichier produit par `reconcile --out`")
    app.add_argument("--accept", action="append", default=[], help="proposal_id à approuver (répétable)")
    app.add_argument("--approver", required=True)
    app.add_argument("--out", required=True)

    for name, helptext in (
        ("disable-password", "Désactiver le mot de passe d'un compte lié au SSO (phase 3)"),
        ("enable-password", "Réactiver le mot de passe d'un compte (retour arrière)"),
    ):
        cmd = commands.add_parser(name, help=helptext)
        cmd.add_argument("--user", required=True, help="E-mail du compte")
        cmd.add_argument("--apply", action="store_true")
        cmd.add_argument("--confirm-backup", default=None)
        cmd.add_argument("--operator", default=None)

    bg = commands.add_parser("break-glass", help="Désigner / retirer le compte administrateur hors SSO")
    bg.add_argument("--user", required=True, help="E-mail du compte")
    bg.add_argument("--unset", action="store_true")
    bg.add_argument("--apply", action="store_true")
    bg.add_argument("--operator", default=None)


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise Refused(f"Fichier illisible : {path}") from exc


def _emit(data: Any, out: str | None) -> None:
    text_out = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if out:
        Path(out).write_text(text_out, encoding="utf-8")
    else:
        sys.stdout.write(text_out)


def _require_operator(args: argparse.Namespace) -> str:
    if not (args.operator or "").strip():
        raise Refused("Écriture refusée : --operator <nom> est obligatoire (audit)")
    return str(args.operator).strip()


async def run_accounts(args: argparse.Namespace) -> int:
    from app.db import get_sessionmaker

    try:
        return await _run(args, get_sessionmaker)
    except Refused as exc:
        print(f"Refusé : {exc}", file=sys.stderr)
        return EXIT_USAGE


async def _run(args: argparse.Namespace, get_sessionmaker: Any) -> int:
    command = args.accounts_command
    if command == "approve":
        key = settings.accounts_approval_key
        if not key:
            raise Refused("ORBIT_ACCOUNTS_APPROVAL_KEY est requis pour signer une approbation")
        proposals = json.loads(_read(args.proposal))
        approval = make_approval(proposals, args.accept, args.approver, key)
        _emit(approval, args.out)
        return EXIT_OK
    async with get_sessionmaker()() as session:
        if command == "inventory":
            inventory = await build_inventory(session, emails=args.emails)
            _emit(inventory_csv(inventory) if args.format == "csv" else inventory, args.out)
            return EXIT_OK
        if command == "reconcile":
            issuer, subjects = load_export(Path(args.idp_export))
            if args.apply:
                operator = _require_operator(args)
                check_backup(args.confirm_backup)
                if not args.approval:
                    raise Refused("--apply exige --approval <fichier d'approbation signé>")
                approval = read_approval(Path(args.approval), settings.accounts_approval_key, issuer)
                proposals = await build_proposals(
                    session, issuer, subjects, allowed_domains=args.allowed_domain
                )
                done = await apply_links(session, approval, proposals, operator=operator)
                _emit({"mode": "apply", "linked": done}, args.out)
                return EXIT_OK
            await session.execute(text("SET TRANSACTION READ ONLY"))
            proposals = await build_proposals(session, issuer, subjects, allowed_domains=args.allowed_domain)
            _emit(proposals, args.out)
            return EXIT_OK
        if command in ("disable-password", "enable-password"):
            disable = command == "disable-password"
            operator = _require_operator(args) if args.apply else ""
            if args.apply and disable:
                check_backup(args.confirm_backup)  # the rollback needs no backup
            _emit(
                await set_password_login(
                    session, args.user, disable=disable, apply=args.apply, operator=operator
                ),
                None,
            )
            return EXIT_OK
        if command == "break-glass":
            operator = _require_operator(args) if args.apply else ""
            _emit(
                await set_break_glass(
                    session, args.user, enable=not args.unset, apply=args.apply, operator=operator
                ),
                None,
            )
            return EXIT_OK
    return EXIT_USAGE
