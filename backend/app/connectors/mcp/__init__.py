"""MCP connectors (docs/FEATURES.md F6): generic ``mcp`` connector type driven by curated presets."""

from __future__ import annotations

from app.connectors.mcp.connector import McpConnector
from app.connectors.mcp.presets import PRESETS, Preset, get_preset

__all__ = ["PRESETS", "McpConnector", "Preset", "get_preset"]
