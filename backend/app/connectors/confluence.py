"""Confluence connector — Cloud or Data Center (docs/FEATURES.md F5).

Configuration: ``base_url`` (``https://acme.atlassian.net/wiki`` or ``https://confluence.acme.fr``),
``deployment`` (``cloud`` | ``datacenter``), ``email`` (Cloud: e-mail + API token, Basic auth; empty: the
secret is a personal access token, Bearer auth) and ``space_keys``.
Incremental sync: CQL ``lastmodified > "<cursor>"`` (ordered by ``lastmodified``); pages are ingested as
HTML (storage format) and turned into text by the ingestion pipeline. Deletions: pages known to ORBIT but
absent from the scope listing are checked one by one (404 or ``trashed`` ⇒ forgotten).
"""

from __future__ import annotations

import base64
import html
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from app.connectors.base import (
    BaseConnector,
    Change,
    ConnectorError,
    CredentialCheck,
    NotFoundError,
    ScopeOption,
    deployment_field,
    list_field,
    parse_datetime,
    text_field,
    url_field,
)
from app.enums import SourceKind

PAGE_SIZE = 50
ID_PAGE_SIZE = 200
MAX_PAGES = 10_000
#: CQL dates are expressed in the account's time zone: re-read a safety window (unchanged pages are
#: deduplicated by content hash, so the overlap only costs requests).
OVERLAP = timedelta(hours=24)


def basic_auth(user: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


def cql_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class ConfluenceConnector(BaseConnector):
    type = "confluence"
    label = "Confluence"
    source_kind = SourceKind.document

    @classmethod
    def validate_config(cls, config: dict[str, Any], *, require_scope: bool) -> dict[str, Any]:
        base = url_field(config)
        deployment = deployment_field(config)
        host = urlsplit(base).hostname or ""
        if deployment == "cloud" and host.endswith(".atlassian.net") and not base.endswith("/wiki"):
            base += "/wiki"
        clean = {
            "base_url": base,
            "deployment": deployment,
            "email": text_field(
                config, "email", "E-mail du compte", required=deployment == "cloud", max_length=320
            ),
            "space_keys": [key.upper() for key in list_field(config, "space_keys", "Espaces")],
        }
        if require_scope and not clean["space_keys"]:
            raise ValueError("Choisissez au moins un espace Confluence")
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
        return f"{self.root}/rest/api"

    def scope_label(self) -> str:
        return ", ".join(self.config.get("space_keys") or [])

    def _follow(self, next_link: str) -> str:
        """Absolute URL of a ``_links.next`` (relative to the site root, same host only)."""
        if next_link.startswith("http"):
            if urlsplit(next_link).hostname != urlsplit(self.root).hostname:
                raise ConnectorError("Lien de pagination Confluence inattendu (hôte refusé)")
            return next_link
        root = self.root
        if next_link.startswith("/wiki/") and root.endswith("/wiki"):
            root = root[: -len("/wiki")]
        return root + next_link

    async def test(self) -> CredentialCheck:
        account: str | None = None
        try:
            user = await self.http.get_json(f"{self.api}/user/current")
            account = user.get("displayName") or user.get("username") or user.get("email")
        except NotFoundError:
            account = None
        spaces = await self.http.get_json(f"{self.api}/space", params={"limit": "100", "type": "global"})
        options = [
            ScopeOption(str(space.get("key")), str(space.get("name") or space.get("key")), "space")
            for space in spaces.get("results") or []
            if space.get("key")
        ]
        who = f" en tant que {account}" if account else ""
        return CredentialCheck(
            ok=True,
            message=f"Connexion à Confluence réussie{who} : {len(options)} espace(s) visible(s)",
            account=account,
            scope_options=options,
        )

    def _scope_cql(self) -> str:
        keys = [str(k) for k in self.config.get("space_keys") or []]
        if not keys:
            raise ConnectorError("Aucun espace Confluence sélectionné")
        return f"type = page AND space IN ({', '.join(cql_quote(k) for k in keys)})"

    async def _search(self, cql: str, *, expand: str | None, limit: int) -> AsyncIterator[dict[str, Any]]:
        """Pages matching ``cql``: follows ``_links.next`` (Cloud cursor), else ``start`` offsets (DC)."""
        params: dict[str, str] = {"cql": cql, "limit": str(limit)}
        if expand:
            params["expand"] = expand
        url = f"{self.api}/content/search"
        query: dict[str, str] | None = params
        start = 0
        for _ in range(MAX_PAGES):
            page = await self.http.get_json(url, params=query)
            results = list(page.get("results") or [])
            for result in results:
                yield result
            next_link = (page.get("_links") or {}).get("next")
            if not results:
                break
            if next_link:
                url, query = self._follow(str(next_link)), None
            elif query is not None and len(results) >= limit:
                start += len(results)
                query = {**params, "start": str(start)}
            else:
                break

    async def changes(self, cursor: dict[str, Any]) -> AsyncIterator[Change]:
        since = parse_datetime(cursor.get("last_modified"))
        cql = self._scope_cql()
        if since is not None:
            cql += f' AND lastmodified > "{(since.astimezone(UTC) - OVERLAP).strftime("%Y/%m/%d %H:%M")}"'
        cql += " ORDER BY lastmodified ASC"
        latest: datetime | None = since
        async for page in self._search(cql, expand="body.storage,version,space", limit=PAGE_SIZE):
            change = self._page_change(page)
            if change is None:
                continue
            if change.updated_at and (latest is None or change.updated_at > latest):
                latest = change.updated_at
            yield change
        self.next_cursor = {"last_modified": latest.isoformat() if latest else None}

    def _page_change(self, page: dict[str, Any]) -> Change | None:
        page_id = str(page.get("id") or "")
        if not page_id:
            return None
        title = str(page.get("title") or f"Page {page_id}")
        if page.get("status") in ("trashed", "deleted"):
            return Change(page_id, deleted=True)
        body = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
        version = page.get("version") or {}
        webui = (page.get("_links") or {}).get("webui")
        document = (
            f'<html><head><meta charset="utf-8"><title>{html.escape(title)}</title></head>'
            f"<body><h1>{html.escape(title)}</h1>{body}</body></html>"
        )
        return Change(
            page_id,
            title=title,
            mime_type="text/html",
            data=document.encode("utf-8"),
            filename=f"{title[:120]}.html",
            uri=f"{self.root}{webui}" if webui else None,
            author=((version.get("by") or {}).get("displayName")),
            updated_at=parse_datetime(version.get("when")),
            metadata={
                "connector": "confluence",
                "page_id": page_id,
                "space": (page.get("space") or {}).get("key"),
                "version": version.get("number"),
            },
        )

    async def confirm_deleted(self, known_ids: set[str]) -> list[str]:
        if not known_ids:
            return []
        present: set[str] = set()
        async for page in self._search(self._scope_cql(), expand=None, limit=ID_PAGE_SIZE):
            present.add(str(page.get("id")))
        deleted: list[str] = []
        for page_id in sorted(known_ids - present):
            try:
                page = await self.http.get_json(
                    f"{self.api}/content/{quote(page_id, safe='')}", params={"status": "any"}
                )
            except NotFoundError:
                deleted.append(page_id)
                continue
            if page.get("status") in ("trashed", "deleted"):
                deleted.append(page_id)
        return deleted
