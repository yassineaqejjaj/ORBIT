"""Administration CLI.

``python -m app.admin eval --project <slug> [--set <nom>] [--k 5] [--min-recall 0.6] [--as <email>]``
runs the project's golden sets synchronously (docs/AI_CONTEXT_ENGINEERING.md §E1) and exits with:

* ``0`` — every run passed (mean recall ≥ threshold);
* ``1`` — at least one run is below the threshold (blocking in CI);
* ``2`` — usage error (unknown project / set / user, no golden set).

``python -m app.admin purge-forgotten [--project <slug>] [--dry-run] [--json]`` rewrites, at rest, the
persisted contexts and snapshots that still quote forgotten chunks or memory (NOV-97). Idempotent; to run
after restoring a backup (docs/FEATURES.md, « Oubli sélectif »).

``python -m app.admin keys list [--workspace <uuid>] [--project <slug>] [--json]`` lists the agent
keys by workspace / project (role, clearance, age, last use, expiry, status) **without any secret**;
``keys revoke-misplaced [--dry-run]`` revokes the keys whose workspace is no longer their project's
(NOV-112).

``python -m app.admin accounts <inventory|reconcile|approve|disable-password|enable-password|
break-glass>`` is the account migration tool of ADR 001 §8 (NOV-113): read-only unless ``--apply``;
see ``docs/ACCOUNTS_MIGRATION.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.db import dispose_engine, get_sessionmaker
from app.evaluation import bench
from app.models import EvalSet, MemoryItem, Project, ProjectMember, User


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.admin", description="Administration ORBIT")
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("eval", help="Exécuter le banc d'évaluation d'un projet (CI)")
    ev.add_argument("--project", required=True, help="Slug du projet")
    ev.add_argument("--set", dest="set_name", default=None, help="Nom du jeu (défaut : tous)")
    ev.add_argument("--k", type=int, default=None, help="k de rappel@k / nDCG@k (défaut ORBIT_EVAL_K)")
    ev.add_argument(
        "--min-recall", type=float, default=None, help="Seuil bloquant (défaut ORBIT_EVAL_MIN_RECALL)"
    )
    ev.add_argument("--as", dest="as_email", default=None, help="Utilisateur évaluateur (défaut : un owner)")
    ev.add_argument("--json", action="store_true", help="Sortie JSON")
    pf = sub.add_parser(
        "purge-forgotten",
        help="Réécrire les contextes et snapshots persistés citant du contenu oublié (idempotent)",
    )
    pf.add_argument(
        "--project", default=None, help="Slug du projet (défaut : tous, mémoire d'organisation incluse)"
    )
    pf.add_argument("--dry-run", action="store_true", help="Compter sans rien écrire")
    pf.add_argument("--json", action="store_true", help="Sortie JSON")
    keys = sub.add_parser(
        "keys", help="Clés d'agent : inventaire (sans secret) et révocation des clés sorties de leur espace"
    )
    keys_sub = keys.add_subparsers(dest="keys_command", required=True)
    klist = keys_sub.add_parser("list", help="Lister les clés par espace / projet (âge, usage)")
    klist.add_argument("--workspace", default=None, help="Filtrer sur un espace (UUID)")
    klist.add_argument("--project", default=None, help="Filtrer sur un projet (slug)")
    klist.add_argument("--json", action="store_true", help="Sortie JSON")
    krevoke = keys_sub.add_parser(
        "revoke-misplaced", help="Révoquer les clés dont l'espace n'est plus celui de leur projet"
    )
    krevoke.add_argument("--dry-run", action="store_true", help="Lister sans rien écrire")
    krevoke.add_argument("--json", action="store_true", help="Sortie JSON")
    from app.admin import accounts

    accounts.add_parsers(sub)
    return parser


async def run_keys(args: argparse.Namespace) -> int:
    from app.services import agent_keys

    async with get_sessionmaker()() as session:
        if args.keys_command == "list":
            workspace = None
            if args.workspace:
                try:
                    workspace = uuid.UUID(args.workspace)
                except ValueError:
                    print("--workspace attend un UUID", file=sys.stderr)
                    return 2
            rows = await agent_keys.inventory(session, workspace_id=workspace, project_slug=args.project)
        else:
            rows = await agent_keys.revoke_misplaced(session, dry_run=args.dry_run)
    if args.json:
        print(json.dumps([r.as_dict() for r in rows], ensure_ascii=False))
        return 0
    if not rows:
        print("Aucune clé")
    for r in rows:
        used = f"{r.last_used_days_ago} j" if r.last_used_days_ago is not None else "jamais"
        expires = r.expires_at.date().isoformat() if r.expires_at else "sans expiration"
        print(
            f"{r.status:9} {r.key:22} {r.project} ({str(r.workspace_id)[:8]}) {r.role} {r.clearance} "
            f"âge {r.age_days} j, utilisée {used}, {expires}"
        )
    return 0


async def run_purge_forgotten(args: argparse.Namespace) -> int:
    """Replay of forgetting on persisted context: also the step to run after restoring a backup."""
    from app.context.purge import PurgeResult, purge_persisted_context
    from app.enums import ChunkStatus, MemoryStatus
    from app.models import Chunk
    from app.services import audit

    report: list[dict[str, object]] = []
    async with get_sessionmaker()() as session:
        query = select(Project).order_by(Project.created_at)
        if args.project:
            query = query.where(Project.slug == args.project)
        projects = list(await session.scalars(query))
        if args.project and not projects:
            print(f"Projet « {args.project} » introuvable", file=sys.stderr)
            return 2
        scopes: list[tuple[Project | None, uuid.UUID | None]] = [(p, p.id) for p in projects]
        if not args.project:
            scopes.append((None, None))  # organisation-wide memory, served in any project
        for project, project_id in scopes:
            memory_filter = MemoryItem.status == MemoryStatus.forgotten
            memory_scope = (
                MemoryItem.project_id == project_id if project_id else MemoryItem.project_id.is_(None)
            )
            lineages = list(
                await session.scalars(
                    select(MemoryItem.lineage_id).where(memory_filter, memory_scope).distinct()
                )
            )
            chunks = (
                list(
                    await session.scalars(
                        select(Chunk.id).where(
                            Chunk.project_id == project_id, Chunk.status == ChunkStatus.forgotten
                        )
                    )
                )
                if project_id
                else []
            )
            result: PurgeResult = await purge_persisted_context(
                session, project_id, chunk_ids=chunks, lineage_ids=lineages, dry_run=args.dry_run
            )
            label = project.slug if project else "(organisation)"
            report.append({"project": label, "dry_run": args.dry_run, **result.as_dict()})
            if result and not args.dry_run and project is not None:
                await audit.record(
                    session,
                    project.id,
                    audit.Actor.system(),
                    audit.AuditAction.forget_purge,
                    "project",
                    project.id,
                    summary="Rattrapage de l'oubli sur les contextes et snapshots persistés",
                    details=result.as_dict(),
                )
            await session.commit()
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for line in report:
            verb = "à réécrire" if args.dry_run else "réécrits"
            print(
                f"{line['project']} : {line['decisions']} extrait(s), {line['requests']} contexte(s), "
                f"{line['snapshots']} snapshot(s) {verb}"
            )
    return 0


async def _evaluator(session, project: Project, email: str | None) -> User | None:
    if email:
        return await session.scalar(select(User).where(User.email == email.lower().strip()))
    owner = await session.scalar(
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project.id, ProjectMember.role == "owner")
        .order_by(User.created_at)
        .limit(1)
    )
    return owner or await session.scalar(
        select(User).where(User.is_admin.is_(True)).order_by(User.created_at)
    )


async def run_eval(args: argparse.Namespace) -> int:
    async with get_sessionmaker()() as session:
        project = await session.scalar(select(Project).where(Project.slug == args.project))
        if project is None:
            print(f"Projet « {args.project} » introuvable", file=sys.stderr)
            return 2
        query = select(EvalSet).where(EvalSet.project_id == project.id).order_by(EvalSet.name)
        if args.set_name:
            query = query.where(EvalSet.name == args.set_name)
        sets = list(await session.scalars(query))
        if not sets:
            print("Aucun jeu d'évaluation pour ce projet", file=sys.stderr)
            return 2
        user = await _evaluator(session, project, args.as_email)
        if user is None:
            print("Utilisateur évaluateur introuvable", file=sys.stderr)
            return 2
        results = []
        for eval_set in sets:
            run = await bench.create_run(
                session,
                eval_set,
                user=user,
                k=args.k,
                min_recall=args.min_recall,
                trigger="cli",
                enqueue=False,
            )
            await session.commit()
            run = await bench.execute_run(session, run)
            results.append(
                {"set": eval_set.name, "passed": run.passed, "min_recall": run.min_recall, **run.metrics}
            )
    failed = [r for r in results if r["passed"] is False]
    if args.json:
        print(json.dumps({"project": args.project, "runs": results}, ensure_ascii=False))
    else:
        for r in results:
            status = "OK" if r["passed"] else "ÉCHEC" if r["passed"] is False else "—"
            print(
                f"[{status}] {r['set']} : rappel {r['recall']} (seuil {r['min_recall']}), nDCG {r['ndcg']}, "
                f"suffisance {r['sufficiency']}, fidélité des citations {r['citation_faithfulness']}"
            )
    return 1 if failed else 0


async def _main(argv: Sequence[str] | None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "eval":
            return await run_eval(args)
        if args.command == "purge-forgotten":
            return await run_purge_forgotten(args)
        if args.command == "keys":
            return await run_keys(args)
        if args.command == "accounts":
            from app.admin import accounts

            return await accounts.run_accounts(args)
        return 2
    finally:
        await dispose_engine()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
