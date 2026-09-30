"""SQLAlchemy models (ARCHITECTURE §5). Importing this package registers every table on ``Base.metadata``."""

from app.db import Base
from app.models.agent import Agent
from app.models.audit import AuditLog
from app.models.compliance import *  # noqa: F403  (production workstream tables)
from app.models.connector import *  # noqa: F403  (production workstream tables)
from app.models.context import ContextDecision, ContextFeedback, ContextRequest, ContextSnapshot
from app.models.document import Chunk, Document, DocumentVersion
from app.models.governance import Tombstone
from app.models.identity import *  # noqa: F403  (production workstream tables)
from app.models.job import IngestionJob
from app.models.memory import MemoryEvent, MemoryItem, MemoryProvenance, Relation
from app.models.project import Project, ProjectMember
from app.models.source import DEFAULT_ACL, Source, default_acl
from app.models.user import User

__all__ = [
    "DEFAULT_ACL",
    "Agent",
    "AuditLog",
    "Base",
    "Chunk",
    "ContextDecision",
    "ContextFeedback",
    "ContextRequest",
    "ContextSnapshot",
    "Document",
    "DocumentVersion",
    "IngestionJob",
    "MemoryEvent",
    "MemoryItem",
    "MemoryProvenance",
    "Project",
    "ProjectMember",
    "Relation",
    "Source",
    "Tombstone",
    "User",
    "default_acl",
]
