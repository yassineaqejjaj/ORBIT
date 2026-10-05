"""SharePoint / OneDrive connector — Microsoft Graph, OAuth2 client credentials (docs/FEATURES.md F5).

Configuration: ``tenant_id``, ``client_id``, ``site_ids`` (selected sites) and optionally ``drive_ids``
(selected document libraries; every library of the selected sites when empty). Secret: the client secret.
Incremental sync: Graph *delta query* per drive; the cursor stores the ``@odata.deltaLink`` of each drive.
Deleted items (``deleted`` facet) are forgotten in ORBIT.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from app.config import settings
from app.connectors.base import (
    BaseConnector,
    Change,
    ConnectorError,
    CredentialCheck,
    NotFoundError,
    ScopeOption,
    list_field,
    parse_datetime,
    text_field,
)
from app.enums import SourceKind
from app.ingestion.extractors import detect_mime_type, is_supported

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
SCOPE = "https://graph.microsoft.com/.default"
MAX_SITES = 25
MAX_PAGES = 10_000


class SharePointConnector(BaseConnector):
    type = "sharepoint"
    label = "SharePoint / OneDrive"
    source_kind = SourceKind.document

    def __init__(self, config: dict[str, Any], secret: str) -> None:
        super().__init__(config, secret)
        self._token: str | None = None

    @classmethod
    def validate_config(cls, config: dict[str, Any], *, require_scope: bool) -> dict[str, Any]:
        clean = {
            "tenant_id": text_field(config, "tenant_id", "Identifiant du locataire (tenant)", max_length=200),
            "client_id": text_field(
                config, "client_id", "Identifiant de l'application (client)", max_length=200
            ),
            "site_ids": list_field(config, "site_ids", "Sites"),
            "drive_ids": list_field(config, "drive_ids", "Bibliothèques"),
        }
        if require_scope and not (clean["site_ids"] or clean["drive_ids"]):
            raise ValueError("Choisissez au moins un site ou une bibliothèque SharePoint")
        return clean

    def scope_label(self) -> str:
        sites = self.config.get("site_names") or self.config.get("site_ids") or []
        return ", ".join(str(s) for s in sites[:3])

    # -- Graph access ----------------------------------------------------------------------------------
    async def _access_token(self) -> str:
        if self._token:
            return self._token
        tenant = quote(str(self.config.get("tenant_id", "")), safe="")
        try:
            response = await self.http.request(
                "POST",
                f"{LOGIN}/{tenant}/oauth2/v2.0/token",
                data={
                    "client_id": self.config.get("client_id", ""),
                    "client_secret": self.secret,
                    "scope": SCOPE,
                    "grant_type": "client_credentials",
                },
            )
        except ConnectorError as exc:
            if exc.status_code in (400, 401, 403, 404):
                raise ConnectorError(
                    "Identifiants Microsoft Entra refusés : vérifiez le tenant, l'identifiant d'application "
                    "et le secret client",
                    auth=True,
                    status_code=exc.status_code,
                ) from exc
            raise
        token = response.json().get("access_token") if response.content else None
        if not token:
            raise ConnectorError("Jeton Microsoft Graph absent de la réponse", auth=True)
        self._token = str(token)
        return self._token

    async def _get(self, url: str, **kwargs: Any) -> Any:
        if not url.startswith("https://"):
            url = GRAPH + url
        elif not url.startswith("https://graph.microsoft.com/"):
            raise ConnectorError("Lien de pagination Microsoft Graph inattendu (hôte refusé)")
        token = await self._access_token()
        return await self.http.get_json(url, headers={"Authorization": f"Bearer {token}"}, **kwargs)

    async def _sites(self) -> list[dict[str, Any]]:
        site_ids = list(self.config.get("site_ids") or [])
        if site_ids:
            return [
                await self._get(f"/sites/{quote(site_id, safe=',:')}") for site_id in site_ids[:MAX_SITES]
            ]
        page = await self._get("/sites", params={"search": "*", "$top": str(MAX_SITES)})
        return list(page.get("value") or [])[:MAX_SITES]

    async def _site_drives(self, site_id: str) -> list[dict[str, Any]]:
        page = await self._get(f"/sites/{quote(site_id, safe=',:')}/drives")
        return list(page.get("value") or [])

    async def test(self) -> CredentialCheck:
        await self._access_token()
        options: list[ScopeOption] = []
        for site in await self._sites():
            site_id = str(site.get("id") or "")
            if not site_id:
                continue
            name = str(site.get("displayName") or site.get("name") or site_id)
            options.append(ScopeOption(site_id, name, "site", description=str(site.get("webUrl") or "")))
            try:
                drives = await self._site_drives(site_id)
            except NotFoundError:
                drives = []
            for drive in drives:
                options.append(
                    ScopeOption(
                        str(drive.get("id")),
                        str(drive.get("name") or "Documents"),
                        "drive",
                        parent_id=site_id,
                        description=str(drive.get("webUrl") or ""),
                    )
                )
        sites = sum(1 for option in options if option.kind == "site")
        return CredentialCheck(
            ok=True,
            message=f"Connexion à Microsoft Graph réussie : {sites} site(s) accessible(s)",
            scope_options=options,
        )

    async def _drive_ids(self) -> list[str]:
        drive_ids = list(self.config.get("drive_ids") or [])
        if drive_ids:
            return drive_ids
        for site_id in self.config.get("site_ids") or []:
            drive_ids.extend(str(d["id"]) for d in await self._site_drives(site_id) if d.get("id"))
        if not drive_ids:
            raise ConnectorError("Aucune bibliothèque de documents trouvée dans les sites choisis")
        return drive_ids

    # -- Sync ------------------------------------------------------------------------------------------
    async def changes(self, cursor: dict[str, Any]) -> AsyncIterator[Change]:
        deltas: dict[str, str] = dict(cursor.get("delta") or {})
        new_deltas: dict[str, str] = {}
        for drive_id in await self._drive_ids():
            root = f"/drives/{quote(drive_id, safe='!')}/root/delta"
            url: str | None = deltas.get(drive_id) or root
            restarted = False
            for _ in range(MAX_PAGES):
                if url is None:
                    break
                try:
                    page = await self._get(url)
                except NotFoundError:  # 410 resyncRequired: the delta token expired → full enumeration
                    if restarted:
                        raise
                    url, restarted = root, True
                    continue
                for item in page.get("value") or []:
                    change = await self._item_change(drive_id, item)
                    if change is not None:
                        yield change
                url = page.get("@odata.nextLink")
                if url is None and page.get("@odata.deltaLink"):
                    new_deltas[drive_id] = str(page["@odata.deltaLink"])
        self.next_cursor = {"delta": new_deltas}

    async def _item_change(self, drive_id: str, item: dict[str, Any]) -> Change | None:
        item_id = str(item.get("id") or "")
        if not item_id:
            return None
        external_id = f"{drive_id}:{item_id}"
        if "deleted" in item:
            return Change(external_id, deleted=True)
        if "file" not in item:  # folders, root, packages
            return None
        name = str(item.get("name") or item_id)
        declared = (item.get("file") or {}).get("mimeType")
        mime = detect_mime_type(name, declared)
        modified_by = ((item.get("lastModifiedBy") or {}).get("user") or {}).get("displayName")
        change = Change(
            external_id,
            title=name,
            mime_type=mime,
            filename=name,
            uri=item.get("webUrl"),
            author=modified_by,
            updated_at=parse_datetime(item.get("lastModifiedDateTime")),
            metadata={
                "connector": "sharepoint",
                "drive_id": drive_id,
                "item_id": item_id,
                "path": (item.get("parentReference") or {}).get("path"),
            },
        )
        size = int(item.get("size") or 0)
        if not is_supported(mime, name):
            change.skip_reason = f"Format non pris en charge ({name})"
            return change
        if size > settings.max_upload_bytes:
            change.skip_reason = f"Fichier trop volumineux ({name})"
            return change
        try:
            change.data = await self._download(drive_id, item)
        except ConnectorError as exc:
            change.error = exc.message
        return change

    async def _download(self, drive_id: str, item: dict[str, Any]) -> bytes:
        direct = item.get("@microsoft.graph.downloadUrl")
        if isinstance(direct, str) and direct.startswith("https://"):
            response = await self.http.request("GET", direct)  # pre-authenticated, short-lived URL
        else:
            token = await self._access_token()
            response = await self.http.request(
                "GET",
                f"{GRAPH}/drives/{quote(drive_id, safe='!')}/items/{quote(str(item['id']), safe='!')}"
                "/content",
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=True,
            )
        return response.content
