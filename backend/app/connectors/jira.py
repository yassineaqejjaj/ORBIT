"""Jira connector — Cloud or Data Center (docs/FEATURES.md F5).

Configuration: ``base_url``, ``deployment`` (``cloud`` | ``datacenter``), ``email`` (Cloud: e-mail + API
token; empty: personal access token) and ``jql`` (scope). Each issue becomes a ``ticket`` document
(Markdown: fields, description, comments) whose ``external_id`` is the issue key.
Incremental sync: ``(<jql>) AND updated >= "<cursor>" ORDER BY updated ASC``. Cloud uses the
``/search/jql`` endpoint (``nextPageToken``), Data Center ``/search`` (``startAt``). Deletions: keys known
to ORBIT but absent from the JQL listing are checked one by one (404 or key moved ⇒ forgotten).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from app.connectors.base import (
    BaseConnector,
    Change,
    ConnectorError,
    CredentialCheck,
    NotFoundError,
    ScopeOption,
    deployment_field,
    parse_datetime,
    text_field,
    url_field,
)
from app.connectors.confluence import basic_auth
from app.enums import SourceKind

PAGE_SIZE = 50
ID_PAGE_SIZE = 200
MAX_PAGES = 10_000
OVERLAP = timedelta(hours=24)
FIELDS = (
    "summary,description,status,issuetype,priority,assignee,reporter,labels,created,updated,comment,project"
)


def adf_text(node: Any) -> str:
    """Plain text of an Atlassian Document Format node (Cloud v3 payloads)."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(child) for child in node)
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text") or "")
    if kind == "hardBreak":
        return "\n"
    inner = adf_text(node.get("content") or [])
    if kind in ("paragraph", "heading", "blockquote", "codeBlock", "rule"):
        return inner + "\n\n"
    if kind == "listItem":
        return "- " + inner.strip() + "\n"
    return inner


def _name(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("displayName") or user.get("name") or user.get("emailAddress") or "")
    return ""


def _label(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("value") or "")
    return str(value or "")


class JiraConnector(BaseConnector):
    type = "jira"
    label = "Jira"
    source_kind = SourceKind.ticket

    @classmethod
    def validate_config(cls, config: dict[str, Any], *, require_scope: bool) -> dict[str, Any]:
        deployment = deployment_field(config)
        clean = {
            "base_url": url_field(config),
            "deployment": deployment,
            "email": text_field(
                config, "email", "E-mail du compte", required=deployment == "cloud", max_length=320
            ),
            "jql": text_field(config, "jql", "Requête JQL", required=require_scope, max_length=2000),
        }
        if "order by" in clean["jql"].lower():
            raise ValueError("La requête JQL ne doit pas contenir ORDER BY (ajouté automatiquement)")
        return clean

    @classmethod
    def base_url(cls, config: dict[str, Any]) -> str | None:
        return str(config.get("base_url") or "") or None

    def auth_headers(self) -> dict[str, str]:
        email = str(self.config.get("email") or "")
        if email:
            return {"Authorization": basic_auth(email, self.secret)}
        return {"Authorization": f"Bearer {self.secret}"}

    @property
    def root(self) -> str:
        return str(self.config["base_url"]).rstrip("/")

    @property
    def api(self) -> str:
        return f"{self.root}/rest/api/2"

    @property
    def cloud(self) -> bool:
        return self.config.get("deployment", "cloud") == "cloud"

    def scope_label(self) -> str:
        return str(self.config.get("jql") or "")

    async def test(self) -> CredentialCheck:
        me = await self.http.get_json(f"{self.api}/myself")
        account = _name(me) or None
        if self.cloud:
            projects_page = await self.http.get_json(
                f"{self.api}/project/search", params={"maxResults": "50"}
            )
            projects = list(projects_page.get("values") or [])
        else:
            projects = list(await self.http.get_json(f"{self.api}/project") or [])
        options = [
            ScopeOption(str(p.get("key")), f"{p.get('name') or p.get('key')} ({p.get('key')})", "project")
            for p in projects[:100]
            if p.get("key")
        ]
        message = (
            f"Connexion à Jira réussie en tant que {account or 'compte inconnu'} : {len(options)} projet(s)"
        )
        jql = str(self.config.get("jql") or "").strip()
        if jql:
            probe = self._search(f"({jql})", fields="summary", limit=1, max_pages=1)
            try:
                await anext(probe, None)
            except ConnectorError as exc:
                if exc.status_code == 400:
                    return CredentialCheck(
                        ok=False,
                        message=f"Identifiants valides mais requête JQL refusée par Jira : {exc.message}",
                        account=account,
                        scope_options=options,
                    )
                raise
            finally:
                await probe.aclose()
            message += " ; requête JQL valide"
        return CredentialCheck(ok=True, message=message, account=account, scope_options=options)

    async def _search(
        self, jql: str, *, fields: str, limit: int, max_pages: int = MAX_PAGES
    ) -> AsyncIterator[dict[str, Any]]:
        if self.cloud:
            token: str | None = None
            for _ in range(max_pages):
                params = {"jql": jql, "fields": fields, "maxResults": str(limit)}
                if token:
                    params["nextPageToken"] = token
                page = await self.http.get_json(f"{self.api}/search/jql", params=params)
                for issue in page.get("issues") or []:
                    yield issue
                token = page.get("nextPageToken")
                if not token or page.get("isLast"):
                    return
            return
        start = 0
        for _ in range(max_pages):
            params = {"jql": jql, "fields": fields, "maxResults": str(limit), "startAt": str(start)}
            page = await self.http.get_json(f"{self.api}/search", params=params)
            issues = list(page.get("issues") or [])
            for issue in issues:
                yield issue
            start += len(issues)
            if not issues or start >= int(page.get("total") or 0):
                return

    def _jql(self) -> str:
        jql = str(self.config.get("jql") or "").strip()
        if not jql:
            raise ConnectorError("Aucune requête JQL configurée")
        return f"({jql})"

    async def changes(self, cursor: dict[str, Any]) -> AsyncIterator[Change]:
        since = parse_datetime(cursor.get("updated"))
        jql = self._jql()
        if since is not None:
            jql += f' AND updated >= "{(since.astimezone(UTC) - OVERLAP).strftime("%Y/%m/%d %H:%M")}"'
        jql += " ORDER BY updated ASC"
        latest: datetime | None = since
        async for issue in self._search(jql, fields=FIELDS, limit=PAGE_SIZE):
            change = await self._issue_change(issue)
            if change is None:
                continue
            if change.updated_at and (latest is None or change.updated_at > latest):
                latest = change.updated_at
            yield change
        self.next_cursor = {"updated": latest.isoformat() if latest else None}

    async def _comments(self, key: str, fields: dict[str, Any]) -> list[dict[str, Any]]:
        block = fields.get("comment") or {}
        comments = list(block.get("comments") or [])
        total = int(block.get("total") or len(comments))
        while len(comments) < total:
            page = await self.http.get_json(
                f"{self.api}/issue/{quote(key, safe='')}/comment",
                params={"startAt": str(len(comments)), "maxResults": "100"},
            )
            batch = list(page.get("comments") or [])
            if not batch:
                break
            comments.extend(batch)
        return comments

    async def _issue_change(self, issue: dict[str, Any]) -> Change | None:
        key = str(issue.get("key") or "")
        if not key:
            return None
        fields = issue.get("fields") or {}
        summary = str(fields.get("summary") or "")
        change = Change(
            key,
            title=f"{key} — {summary}" if summary else key,
            mime_type="text/markdown",
            uri=f"{self.root}/browse/{key}",
            author=_name(fields.get("reporter")) or None,
            updated_at=parse_datetime(fields.get("updated")),
            metadata={
                "connector": "jira",
                "issue_key": key,
                "project": _label(fields.get("project")) or key.split("-", 1)[0],
                "status": _label(fields.get("status")),
                "issue_type": _label(fields.get("issuetype")),
            },
        )
        try:
            comments = await self._comments(key, fields)
        except ConnectorError as exc:
            change.error = exc.message
            return change
        change.text = self.render(key, fields, comments)
        return change

    @staticmethod
    def render(key: str, fields: dict[str, Any], comments: list[dict[str, Any]]) -> str:
        summary = str(fields.get("summary") or "")
        lines = [f"# {key} — {summary}".rstrip(" —"), ""]
        facts = [
            ("Type", _label(fields.get("issuetype"))),
            ("Statut", _label(fields.get("status"))),
            ("Priorité", _label(fields.get("priority"))),
            ("Assigné à", _name(fields.get("assignee")) or "Non assigné"),
            ("Rapporteur", _name(fields.get("reporter"))),
            ("Étiquettes", ", ".join(str(label) for label in fields.get("labels") or [])),
            ("Créé le", str(fields.get("created") or "")),
            ("Mis à jour le", str(fields.get("updated") or "")),
        ]
        lines += [f"- **{label}** : {value}" for label, value in facts if value]
        description = adf_text(fields.get("description")).strip()
        lines += ["", "## Description", "", description or "_Aucune description._"]
        if comments:
            lines += ["", f"## Commentaires ({len(comments)})"]
            for comment in comments:
                when = str(comment.get("created") or "")[:16].replace("T", " ")
                lines += ["", f"### {_name(comment.get('author')) or 'Anonyme'} — {when}", ""]
                lines.append(adf_text(comment.get("body")).strip())
        return "\n".join(lines).strip() + "\n"

    async def confirm_deleted(self, known_ids: set[str]) -> list[str]:
        if not known_ids:
            return []
        present: set[str] = set()
        async for issue in self._search(self._jql(), fields="updated", limit=ID_PAGE_SIZE):
            present.add(str(issue.get("key")))
        deleted: list[str] = []
        for key in sorted(known_ids - present):
            try:
                issue = await self.http.get_json(
                    f"{self.api}/issue/{quote(key, safe='')}", params={"fields": "updated"}
                )
            except NotFoundError:
                deleted.append(key)
                continue
            if str(issue.get("key") or key) != key:  # moved to another project: the new key is synced
                deleted.append(key)
        return deleted
