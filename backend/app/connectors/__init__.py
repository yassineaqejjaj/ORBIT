"""Connectors to external content systems (docs/FEATURES.md F5): SharePoint/OneDrive, Confluence, Jira."""

from __future__ import annotations

from app.connectors.base import BaseConnector
from app.connectors.confluence import ConfluenceConnector
from app.connectors.jira import JiraConnector
from app.connectors.sharepoint import SharePointConnector

REGISTRY: dict[str, type[BaseConnector]] = {
    cls.type: cls for cls in (SharePointConnector, ConfluenceConnector, JiraConnector)
}

__all__ = ["REGISTRY", "BaseConnector", "ConfluenceConnector", "JiraConnector", "SharePointConnector"]
