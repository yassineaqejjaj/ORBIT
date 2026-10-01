"""Audit actions of the identity workstream (stored in ``audit_log.action``)."""

from __future__ import annotations

from enum import StrEnum


class IdentityAuditAction(StrEnum):
    login_locked = "auth.login_locked"
    password_change = "auth.password_change"
    password_change_required = "auth.password_change_required"
    session_revoke = "auth.session_revoke"
