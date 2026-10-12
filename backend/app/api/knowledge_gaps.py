"""Knowledge gaps: what the project's memory keeps failing to answer.

Aggregated from the sufficiency verdict ORBIT already records on every context request. Editors only: it shows
what other people asked for, reduced to topics (never the question itself). Contributors are suggested from
the memory the caller can see, so nobody is named through an item they could not open.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import select

from app.context.knowledge_gaps import MissingTopic, aggregate, topic_key
from app.context.textutils import key_terms
from app.deps import EditorAccess, SessionDep
from app.enums import ActorType, MemoryKind, MemoryScope, MemoryStatus
from app.errors import conflict
from app.memory import lifecycle
from app.memory.lifecycle import utcnow
from app.memory.serializers import actor_labels, serialize_item
from app.memory.visibility import MemoryViewer, visibility_clause
from app.models import ContextRequest
from app.models import MemoryItem as MemoryItemRow
from app.schemas.common import ApiModel, InputModel
from app.schemas.memory import MemoryIn
from app.schemas.memory import MemoryItem as MemoryItemOut

router = APIRouter(prefix="/projects/{slug}/knowledge-gaps", tags=["knowledge-gaps"])

SCAN_LIMIT = 2000  # most recent requests read per call
CONTRIBUTOR_GAPS = 10  # contributors are only looked up for the most frequent gaps
CONTRIBUTORS = 3
CANDIDATES = 400  # most recent visible items compared with a topic
KEY_TERMS = 6
GAP_TAG = "knowledge-gap"


class Contributor(ApiModel):
    user_id: str
    label: str
    items: int


class KnowledgeGap(ApiModel):
    key: str
    topic: str
    requests: int
    askers: int
    first_seen: str
    last_seen: str
    avg_score: float
    trend: str
    severity: str
    contributors: list[Contributor] = Field(default_factory=list)
    requested: bool = False


class KnowledgeGaps(ApiModel):
    window_days: int
    analysed_requests: int
    gaps: list[KnowledgeGap]


class GapRequestIn(InputModel):
    topic: str = Field(min_length=3, max_length=300)


def _missing(requests: list[ContextRequest]) -> list[MissingTopic]:
    found: list[MissingTopic] = []
    for request in requests:
        sufficiency = (request.params or {}).get("sufficiency") or {}
        if sufficiency.get("verdict") not in ("partial", "insufficient"):
            continue
        asker = str(request.user_id or request.agent_id or "") or None
        for topic in sufficiency.get("missing_subtopics") or []:
            if isinstance(topic, str) and topic.strip():
                found.append(
                    MissingTopic(
                        topic.strip()[:300], request.created_at, asker, float(sufficiency.get("score") or 0)
                    )
                )
    return found


async def _contributors(session, viewer: MemoryViewer, topic: str) -> list[Contributor]:
    """People who wrote the closest memory the caller can see.

    Titles are compared with the topic on the same accent-free stemmed terms the topics are grouped by.
    """
    wanted = set(key_terms(topic)[:KEY_TERMS])
    if not wanted:
        return []
    rows = (
        await session.scalars(
            select(MemoryItemRow)
            .where(
                visibility_clause(viewer),
                MemoryItemRow.is_current.is_(True),
                MemoryItemRow.status.in_((MemoryStatus.proposed, MemoryStatus.validated)),
                MemoryItemRow.kind != MemoryKind.action,  # a documentation request is not knowledge
            )
            .order_by(MemoryItemRow.updated_at.desc())
            .limit(CANDIDATES)
        )
    ).all()
    related = [r for r in rows if len(wanted & set(key_terms(r.title))) >= min(2, len(wanted))]
    counts = Counter(
        r.created_by_id for r in related if r.created_by_type == ActorType.user and r.created_by_id
    )
    top = counts.most_common(CONTRIBUTORS)
    labels = await actor_labels(session, [(ActorType.user, uid) for uid, _ in top])
    return [
        Contributor(user_id=str(uid), label=labels.get((ActorType.user, uid), "Membre"), items=n)
        for uid, n in top
    ]


@router.get("", response_model=KnowledgeGaps, summary="Lacunes de connaissance récurrentes")
async def knowledge_gaps(
    access: EditorAccess,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> KnowledgeGaps:
    now = utcnow()
    requests = list(
        await session.scalars(
            select(ContextRequest)
            .where(
                ContextRequest.project_id == access.project_id,
                ContextRequest.created_at >= now - timedelta(days=days),
            )
            .order_by(ContextRequest.created_at.desc())
            .limit(SCAN_LIMIT)
        )
    )
    gaps = aggregate(_missing(requests), now, days)[:limit]
    viewer = MemoryViewer.from_access(access)
    open_titles = set(
        await session.scalars(
            select(MemoryItemRow.title).where(
                MemoryItemRow.project_id == access.project_id,
                MemoryItemRow.is_current.is_(True),
                MemoryItemRow.kind == MemoryKind.action,
                MemoryItemRow.status.in_((MemoryStatus.proposed, MemoryStatus.validated)),
                MemoryItemRow.tags.contains([GAP_TAG]),
            )
        )
    )
    out: list[KnowledgeGap] = []
    for index, gap in enumerate(gaps):
        contributors = await _contributors(session, viewer, gap["topic"]) if index < CONTRIBUTOR_GAPS else []
        out.append(
            KnowledgeGap(
                **{
                    **gap,
                    "first_seen": gap["first_seen"].isoformat(),
                    "last_seen": gap["last_seen"].isoformat(),
                },
                contributors=contributors,
                requested=_title(gap["topic"]) in open_titles,
            )
        )
    return KnowledgeGaps(window_days=days, analysed_requests=len(requests), gaps=out)


def _title(topic: str) -> str:
    return f"Documenter : {topic}"[:300]


@router.post(
    "/request", response_model=MemoryItemOut, status_code=201, summary="Demander à documenter une lacune"
)
async def request_documentation(
    body: GapRequestIn, access: EditorAccess, session: SessionDep
) -> MemoryItemOut:
    """Opens a proposed *action* in the memory review, so the gap is owned instead of staying a statistic."""
    topic = " ".join(body.topic.split())
    if not topic_key(topic):
        raise conflict("Ce sujet est trop vague pour être documenté.")
    title = _title(topic)
    existing = await session.scalar(
        select(MemoryItemRow.id).where(
            MemoryItemRow.project_id == access.project_id,
            MemoryItemRow.is_current.is_(True),
            MemoryItemRow.title == title,
            MemoryItemRow.status.in_((MemoryStatus.proposed, MemoryStatus.validated)),
        )
    )
    if existing is not None:
        raise conflict("Une demande de documentation existe déjà pour ce sujet.")
    item = await lifecycle.create_item(
        session,
        project_id=access.project_id,
        data=MemoryIn(
            scope=MemoryScope.project,
            kind=MemoryKind.action,
            title=title,
            content=(
                f"Le contexte servi aux agents ne couvre pas régulièrement : {topic}. "
                "Documenter ce sujet (décision, règle ou source)."
            ),
            tags=[GAP_TAG],
            status="proposed",
        ),
        actor=access.principal.actor,
    )
    await session.commit()
    return await serialize_item(session, item)
