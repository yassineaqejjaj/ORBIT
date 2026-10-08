"""Administration CLI.

``python -m app.admin eval --project <slug> [--set <nom>] [--k 5] [--min-recall 0.6] [--as <email>]``
runs the project's golden sets synchronously (docs/AI_CONTEXT_ENGINEERING.md §E1) and exits with:

* ``0`` — every run passed (mean recall ≥ threshold);
* ``1`` — at least one run is below the threshold (blocking in CI);
* ``2`` — usage error (unknown project / set / user, no golden set).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from sqlalchemy import select

from app.db import dispose_engine, get_sessionmaker
from app.evaluation import bench
from app.models import EvalSet, Project, ProjectMember, User


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
    return parser


async def _evaluator(session, project: Project, email: str | None) -> User | None:  # type: ignore[no-untyped-def]
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
        return 2
    finally:
        await dispose_engine()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
