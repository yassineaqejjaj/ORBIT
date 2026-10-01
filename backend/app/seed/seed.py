"""Demo seed « Atlas » (docs/DEMO.md) — ``python -m app.seed [--reset] [--api http://localhost:8000]``.

The seed goes **through the real REST API** (authentication, ingestion by the worker, memory lifecycle,
context assembly, snapshots) so that it proves the platform works end to end. Only the operations the
API does not expose use the service layer directly (see :mod:`app.seed.direct`): the reset, organisation
level memory, the forced expiry of a session and the redistribution of the demo request timestamps.

It is idempotent: existing users, project, members, agents, sources, documents, memory items and sessions
are reused; the usage history is only replayed on an empty project (or after ``--reset``). Any optional
step that fails is reported as a warning and the seed carries on; the final summary lists the warnings.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.seed import manifest as mf

AGENTS_FILE = Path(__file__).resolve().parents[2] / ".seed-agents.json"
#: Double-submit CSRF (same names as app.security; not imported so the seed runs without app settings).
CSRF_COOKIE_NAME = "orbit_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
DEFAULT_API = os.environ.get("ORBIT_SEED_API", "http://localhost:8000")
MEMORY_STATUSES = ("proposed", "validated", "superseded", "obsolete", "forgotten")
DOCUMENT_STATUSES = ("pending", "processing", "indexed", "failed", "forgotten")
PAGE_SIZE = 100


# --------------------------------------------------------------------------------------------------
# Console output


def say(message: str = "") -> None:
    print(message, flush=True)


def title(message: str) -> None:
    say()
    say(f"== {message}")


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# --------------------------------------------------------------------------------------------------
# HTTP


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, detail: str) -> None:
        super().__init__(f"{method} {path} → {status} : {detail}")
        self.status = status
        self.detail = detail


class SeedAbort(RuntimeError):
    """A mandatory step failed: the seed cannot continue."""


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase
    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
        return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)[:300]
    return json.dumps(body, ensure_ascii=False)[:300]


class Api:
    """Thin JSON client bound to one identity (user session cookie or agent API key)."""

    def __init__(
        self,
        base_url: str,
        *,
        label: str,
        api_key: str | None = None,
        timeout: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Accept": "application/json", "User-Agent": "orbit-seed/1.0"}
        if api_key:
            headers["X-Orbit-Key"] = api_key
        self.label = label
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api/v1", headers=headers, timeout=timeout, transport=transport
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        csrf = self.client.cookies.get(CSRF_COOKIE_NAME)
        if csrf and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            # Same double-submit behaviour as the web UI (docs/PRODUCTION.md §0 « CSRF »).
            kwargs["headers"] = {**kwargs.get("headers", {}), CSRF_HEADER_NAME: csrf}
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(method, path, 0, f"API injoignable ({exc.__class__.__name__})") from exc
        if response.status_code >= 400:
            raise ApiError(method, path, response.status_code, _error_detail(response))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return await self.request("GET", path, params=clean)

    async def post(self, path: str, body: Any = None, **kwargs: Any) -> Any:
        if body is not None:
            kwargs["json"] = body
        return await self.request("POST", path, **kwargs)

    async def patch(self, path: str, body: Any) -> Any:
        return await self.request("PATCH", path, json=body)

    async def pages(self, path: str, **params: Any) -> list[dict[str, Any]]:
        """Every item of a paginated ``Page<T>`` endpoint."""
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await self.get(path, page=page, page_size=PAGE_SIZE, **params)
            batch = data.get("items", []) if isinstance(data, dict) else list(data or [])
            items.extend(batch)
            total = int(data.get("total", len(items))) if isinstance(data, dict) else len(items)
            if not batch or len(items) >= total:
                return items
            page += 1

    async def total(self, path: str, **params: Any) -> int:
        data = await self.get(path, page=1, page_size=1, **params)
        return int(data.get("total", 0)) if isinstance(data, dict) else len(data or [])


# --------------------------------------------------------------------------------------------------
# Seeder


@dataclass(slots=True)
class RequestResult:
    index: int
    spec: dict[str, Any]
    request_id: uuid.UUID
    created_at: datetime
    exclusion_summary: dict[str, int]
    included: int
    tokens: int
    snapshot: dict[str, Any] | None


@dataclass
class Seeder:
    api_url: str
    admin_email: str
    admin_password: str
    reset: bool = False
    jobs_timeout: float = 900.0
    replay_history: bool = True
    transport: httpx.AsyncBaseTransport | None = None
    poll_interval: float = 2.0
    now: datetime = field(default_factory=mf.now_utc)
    manifest: dict[str, Any] = field(default_factory=mf.load_manifest)

    warnings: list[str] = field(default_factory=list)
    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    sessions: dict[str, Api] = field(default_factory=dict)
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_clients: dict[str, Api] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[RequestResult] = field(default_factory=list)
    saved_snapshots: dict[str, int] = field(default_factory=dict)
    stats: Counter[str] = field(default_factory=Counter)
    _db: bool | None = None

    # -- helpers -----------------------------------------------------------------------------------

    @property
    def slug(self) -> str:
        return str(self.manifest["project"]["slug"])

    @property
    def base(self) -> str:
        return f"/projects/{self.slug}"

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        say(f"  ⚠ {message}")

    async def optional(self, label: str, coro: Any) -> Any:
        """Run an optional step: log a warning instead of failing."""
        try:
            return await coro
        except ApiError as exc:
            self.warn(f"{label} : {exc}")
        except Exception as exc:
            self.warn(f"{label} : {exc.__class__.__name__} — {exc}")
        return None

    async def db(self) -> bool:
        """Is the service layer (database, index, Valkey) reachable from this process?"""
        if self._db is None:
            from app.seed.direct import db_available

            self._db = await db_available()
            if not self._db:
                self.warn(
                    "Base de données injoignable depuis ce processus : les étapes hors API sont ignorées "
                    "(lancez le seed dans le conteneur api : make seed)"
                )
        return self._db

    async def login(self, email: str, password: str, label: str) -> Api:
        api = Api(self.api_url, label=label, transport=self.transport)
        await api.post("/auth/login", {"email": email, "password": password})
        return api

    async def as_user(self, key: str) -> Api:
        if key not in self.sessions:
            user = self.manifest_user(key)
            self.sessions[key] = await self.login(
                user["email"], self.manifest["demo_password"], user["full_name"]
            )
        return self.sessions[key]

    def manifest_user(self, key: str) -> dict[str, Any]:
        return mf.by_key(self.manifest["users"])[key]

    def user_id(self, key: str) -> str:
        return str(self.users[key]["id"])

    def agent_api(self, key: str) -> Api:
        if key not in self.agent_clients:
            raise SeedAbort(f"Clé API indisponible pour l'agent « {key} »")
        return self.agent_clients[key]

    # -- run ---------------------------------------------------------------------------------------

    async def run(self) -> int:
        errors = mf.validate_manifest(self.manifest)
        if errors:
            for error in errors:
                say(f"  ✗ {error}")
            raise SeedAbort("Le manifeste des données de démonstration est incohérent")

        say(f"ORBIT — seed de démonstration « {self.manifest['project']['name']} » (données fictives)")
        say(f"API : {self.api_url} · J = {self.now:%Y-%m-%d %H:%M} UTC")
        admin = await self._admin_login()
        self.sessions["admin"] = admin
        try:
            if self.reset:
                await self.reset_demo()
            await self.ensure_users(admin)
            await self.ensure_project()
            await self.optional("Membres", self.ensure_members())
            await self.optional("Agents", self.ensure_agents())
            await self.optional("Sources", self.ensure_sources())
            for phase in mf.phases(self.manifest):
                await self.optional(f"Ingestion (phase {phase})", self.ingest_phase(phase))
                await self.optional(f"Attente du worker (phase {phase})", self.wait_for_jobs(phase))
                await self.optional(f"Validations (phase {phase})", self.apply_validations(phase))
            await self.optional("Mémoire", self.seed_memory())
            await self.optional("Sessions", self.seed_sessions())
            if self.replay_history:
                await self.optional("Historique des contextes", self.replay_context_history())
                await self.optional("Redistribution des horodatages", self.redistribute_timestamps())
            await self.optional("Résumé", self.print_summary())
        finally:
            for api in [*self.sessions.values(), *self.agent_clients.values()]:
                await api.close()
            if self._db:
                from app.seed.direct import close_resources

                await close_resources()
        return 0

    async def _admin_login(self) -> Api:
        title("Connexion administrateur")
        try:
            admin = await self.login(self.admin_email, self.admin_password, "Administrateur")
        except ApiError as exc:
            raise SeedAbort(
                f"Connexion de l'administrateur {self.admin_email} impossible : {exc.detail}"
            ) from exc
        say(f"  ✓ {self.admin_email}")
        return admin

    # -- reset -------------------------------------------------------------------------------------

    async def reset_demo(self) -> None:
        title("Réinitialisation (--reset)")
        if not await self.db():
            raise SeedAbort("--reset nécessite l'accès à la base de données (lancez : make seed)")
        from app.seed.direct import reset_demo

        emails = [user["email"] for user in self.manifest["users"]]
        org_titles = [item["title"] for item in self.manifest["memory"] if item.get("org")]
        counts = await reset_demo(self.slug, emails, org_titles)
        say(
            f"  ✓ projet supprimé : {counts['projects']} · utilisateurs : {counts['users']} · "
            f"mémoire organisation : {counts['org_memory']} · documents d'index : {counts['index_docs']} · "
            f"clés de session : {counts['sessions']}"
        )
        with contextlib.suppress(FileNotFoundError):
            AGENTS_FILE.unlink()

    # -- users, project, members, agents, sources --------------------------------------------------

    async def ensure_users(self, admin: Api) -> None:
        title("Utilisateurs")
        password = self.manifest["demo_password"]
        me = await admin.get("/auth/me")
        target = int(self.manifest.get("admin_clearance", 3))
        if int(me.get("clearance", 0)) < target:
            await self.optional(
                "Habilitation admin", admin.patch(f"/users/{me['id']}", {"clearance": target})
            )
        for user in self.manifest["users"]:
            found = [
                u for u in await admin.get("/users", q=user["email"]) if u["email"].lower() == user["email"]
            ]
            if found:
                record = await admin.patch(
                    f"/users/{found[0]['id']}",
                    {
                        "full_name": user["full_name"],
                        "clearance": user["clearance"],
                        "password": password,
                        "must_change_password": False,
                    },
                )
                state = "existant"
            else:
                try:
                    record = await admin.post(
                        "/users",
                        {
                            "email": user["email"],
                            "full_name": user["full_name"],
                            "password": password,
                            "clearance": user["clearance"],
                            "is_admin": False,
                            "must_change_password": False,
                        },
                    )
                except ApiError as exc:
                    raise SeedAbort(
                        f"Création de l'utilisateur {user['email']} impossible : {exc.detail}"
                    ) from exc
                state = "créé"
            self.users[user["key"]] = record
            say(f"  ✓ {user['full_name']:<16} {user['email']:<34} C{user['clearance']} ({state})")

    async def ensure_project(self) -> None:
        title("Projet")
        project = self.manifest["project"]
        owner = await self.as_user(project["owner"])
        try:
            current = await owner.get(self.base)
            say(f"  ✓ {self.slug} existant")
        except ApiError as exc:
            if exc.status not in (403, 404):
                raise SeedAbort(f"Lecture du projet impossible : {exc}") from exc
            current = None
            if exc.status == 404:
                try:
                    current = await owner.post(
                        "/projects",
                        {"name": project["name"], "slug": self.slug, "description": project["description"]},
                    )
                    say(f"  ✓ {self.slug} créé — {project['name']}")
                except ApiError as create_exc:
                    if create_exc.status != 409:
                        raise SeedAbort(
                            f"Création du projet impossible : {create_exc.detail}"
                        ) from create_exc
            if current is None:
                # The project exists but the demo owner is not a member (e.g. created by someone else).
                owner_email = self.manifest_user(project["owner"])["email"]
                try:
                    await self.sessions["admin"].post(
                        f"{self.base}/members", {"email": owner_email, "role": "owner"}
                    )
                    current = await owner.get(self.base)
                except ApiError as admin_exc:
                    raise SeedAbort(
                        f"Accès au projet {self.slug} impossible : {admin_exc.detail}"
                    ) from admin_exc
                say(f"  ✓ {self.slug} existant — {owner_email} ajouté comme owner")
        if current.get("slug") != self.slug:
            raise SeedAbort(
                f"Le projet a été créé avec le slug « {current.get('slug')} » au lieu de « {self.slug} »"
            )

    async def ensure_members(self) -> None:
        title("Membres")
        owner = await self.as_user(self.manifest["project"]["owner"])
        members = {m["user"]["email"].lower(): m for m in await owner.get(f"{self.base}/members")}
        for user in self.manifest["users"]:
            member = members.get(user["email"])
            if member is None:
                await owner.post(f"{self.base}/members", {"email": user["email"], "role": user["role"]})
                state = "ajouté"
            elif member["role"] != user["role"]:
                await owner.patch(f"{self.base}/members/{self.user_id(user['key'])}", {"role": user["role"]})
                state = f"rôle {member['role']} → {user['role']}"
            else:
                state = "existant"
            say(f"  ✓ {user['full_name']:<16} {user['role']:<7} ({state})")

    def _load_agent_keys(self) -> dict[str, Any]:
        try:
            data = json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return data.get("agents", {}) if isinstance(data, dict) and data.get("project") == self.slug else {}

    def _save_agent_keys(self, keys: dict[str, Any]) -> None:
        payload = {
            "project": self.slug,
            "api": self.api_url,
            "generated_at": mf.now_utc().isoformat(),
            "notice": "Clés d'agents de démonstration (données fictives). Fichier non versionné.",
            "agents": keys,
        }
        AGENTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            AGENTS_FILE.chmod(0o600)

    async def ensure_agents(self) -> None:
        title("Agents")
        owner = await self.as_user(self.manifest["project"]["owner"])
        stored = self._load_agent_keys()
        existing = {a["name"]: a for a in await owner.get(f"{self.base}/agents") if a.get("active", True)}
        keys: dict[str, Any] = {}
        for spec in self.manifest["agents"]:
            agent = existing.get(spec["name"])
            saved = stored.get(spec["key"], {})
            key = saved.get("api_key")
            if agent is not None and key and str(agent.get("api_key_prefix", "")) in key:
                state = "existant"
            elif agent is not None:
                created = await owner.post(f"{self.base}/agents/{agent['id']}/rotate")
                agent, key, state = created["agent"], created["api_key"], "clé régénérée"
            else:
                created = await owner.post(
                    f"{self.base}/agents",
                    {
                        "name": spec["name"],
                        "kind": spec["kind"],
                        "description": spec["description"],
                        "clearance": spec["clearance"],
                    },
                )
                agent, key, state = created["agent"], created["api_key"], "créé"
            self.agents[spec["key"]] = agent
            self.agent_clients[spec["key"]] = Api(
                self.api_url, label=spec["name"], api_key=key, transport=self.transport
            )
            keys[spec["key"]] = {
                "id": agent["id"],
                "name": spec["name"],
                "kind": spec["kind"],
                "api_key": key,
            }
            say(f"  ✓ {spec['name']:<18} C{spec['clearance']} {key} ({state})")
        self._save_agent_keys(keys)
        say(f"  → clés écrites dans {AGENTS_FILE}")

    async def ensure_sources(self) -> None:
        title("Sources")
        owner = await self.as_user(self.manifest["project"]["owner"])
        existing = {s["name"]: s for s in await owner.get(f"{self.base}/sources")}
        for spec in self.manifest["sources"]:
            source = existing.get(spec["name"])
            state = "existante"
            if source is None:
                body = {
                    "name": spec["name"],
                    "kind": spec["kind"],
                    "description": spec["description"],
                    "default_classification": spec["default_classification"],
                    "default_acl": spec["default_acl"],
                    "config": spec.get("config", {}),
                }
                source = await owner.post(f"{self.base}/sources", body)
                state = "créée"
            self.sources[spec["key"]] = source
            say(f"  ✓ {spec['name']:<24} {spec['kind']:<12} C{spec['default_classification']} ({state})")

    # -- ingestion ---------------------------------------------------------------------------------

    async def _documents_by_source(self, api: Api) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for doc in await api.pages(f"{self.base}/documents"):
            grouped.setdefault(str(doc["source_id"]), []).append(doc)
        return grouped

    async def ingest_phase(self, phase: int) -> None:
        title(f"Ingestion — phase {phase}")
        owner = await self.as_user(self.manifest["project"]["owner"])
        existing = await self._documents_by_source(owner)
        for doc in self.manifest["documents"]:
            if int(doc.get("phase", 1)) != phase:
                continue
            source = self.sources.get(doc["source"])
            if source is None:
                self.warn(f"Document {doc['key']} ignoré : source « {doc['source']} » indisponible")
                continue
            in_source = existing.get(str(source["id"]), [])
            await self.optional(f"Document {doc['key']}", self._ingest_one(owner, doc, source, in_source))

    async def _ingest_one(
        self, owner: Api, doc: dict[str, Any], source: dict[str, Any], in_source: list[dict[str, Any]]
    ) -> None:
        if doc["mode"] == "import":
            wanted = {mf.record_external_id(r) for r in mf.import_records(doc)}
            present = {d.get("external_id") for d in in_source}
            if wanted <= present:
                say(f"  = {doc['file']:<44} déjà importé ({len(wanted)} enregistrements)")
                return
            filename, content, content_type = mf.import_file(doc, self.now)
            result = await owner.post(
                f"{self.base}/documents/import",
                files={"file": (filename, content, content_type)},
                data={"source_kind": doc["source_kind"], "source_id": str(source["id"])},
            )
            self.stats["documents_submitted"] += int(result.get("created", 0)) + int(result.get("updated", 0))
            say(
                f"  + {doc['file']:<44} {result.get('created', 0)} créés, "
                f"{result.get('updated', 0)} mis à jour"
            )
            return

        version = int(doc.get("version", 1))
        match = next(
            (
                d
                for d in in_source
                if d.get("external_id") == doc["external_id"] or d.get("title") == doc["title"]
            ),
            None,
        )
        if match is not None and int(match.get("current_version") or 1) >= version:
            say(f"  = {doc['title'][:44]:<44} déjà présent (v{match.get('current_version')})")
            return
        body = {
            "source_id": str(source["id"]),
            "title": doc["title"],
            "content": mf.document_text(doc, self.now),
            "external_id": doc["external_id"],
            "author": doc.get("author"),
            "uri": doc.get("uri"),
            "classification": doc["classification"],
            "acl_principals": doc["acl"],
            "tags": doc.get("tags", []),
            "source_updated_at": mf.day_at(self.now, int(doc["offset_days"])).isoformat(),
            "metadata": {"seed": "demo-atlas", "demonstrates": doc.get("demonstrates", "")},
        }
        created = await owner.post(
            f"{self.base}/documents/text", {k: v for k, v in body.items() if v is not None}
        )
        self.stats["documents_submitted"] += 1
        marker = f"C{doc['classification']}" + (" ⚠ classifié" if doc["classification"] >= 2 else "")
        say(
            f"  + {doc['title'][:44]:<44} J-{doc['offset_days']:<4} "
            f"v{created.get('current_version', version)} {marker}"
        )

    async def wait_for_jobs(self, phase: int) -> None:
        owner = await self.as_user(self.manifest["project"]["owner"])
        say(f"  … traitement par le worker (phase {phase}, délai max {int(self.jobs_timeout)} s)")
        start = time.monotonic()
        idle_polls = 0
        last = ""
        await asyncio.sleep(self.poll_interval / 2)
        while True:
            queued = await owner.total(f"{self.base}/jobs", status="queued")
            running = await owner.total(f"{self.base}/jobs", status="running")
            line = f"    en file : {queued} · en cours : {running}"
            if line != last:
                say(f"{line} · {int(time.monotonic() - start)} s")
                last = line
            idle_polls = idle_polls + 1 if queued + running == 0 else 0
            if idle_polls >= 2:
                break
            if time.monotonic() - start > self.jobs_timeout:
                self.warn(
                    f"Le worker n'a pas terminé la phase {phase} en {int(self.jobs_timeout)} s "
                    "(le seed continue)"
                )
                break
            await asyncio.sleep(self.poll_interval)
        failed = await owner.total(f"{self.base}/jobs", status="failed")
        if failed:
            self.warn(f"{failed} job(s) d'ingestion en échec (voir l'écran Sources)")
        say(f"  ✓ worker au repos après {int(time.monotonic() - start)} s")

    async def apply_validations(self, phase: int) -> None:
        rules = [r for r in self.manifest.get("validations", []) if int(r["after_phase"]) == phase]
        if not rules:
            return
        owner = await self.as_user(self.manifest["project"]["owner"])
        for rule in rules:
            proposed = await owner.pages(f"{self.base}/memory", kind=rule["kind"], status="proposed")
            needles = [normalize(n) for n in rule["contains"]]
            matched = [
                item
                for item in proposed
                if any(n in normalize(f"{item.get('title', '')} {item.get('content', '')}") for n in needles)
            ]
            for item in matched:
                await self.optional(
                    f"Validation « {item.get('title', '')[:60]} »",
                    owner.post(f"{self.base}/memory/{item['id']}/validate", {"reason": rule["reason"]}),
                )
                self.stats["memory_validated"] += 1
            label = ", ".join(rule["contains"])
            if matched:
                say(f"  ✓ {len(matched)} {rule['kind']}(s) validé(e)s par Camille ({label})")
                continue
            # Explicit "Décision : …" lines are validated at extraction time: nothing left to validate.
            validated = await owner.pages(f"{self.base}/memory", kind=rule["kind"], status="validated")
            already = [
                item
                for item in validated
                if any(n in normalize(f"{item.get('title', '')} {item.get('content', '')}") for n in needles)
            ]
            if already:
                say(f"  ✓ {len(already)} {rule['kind']}(s) déjà validée(s) à l'extraction ({label})")
            else:
                self.warn(f"Aucune proposition « {rule['kind']} » à valider pour : {label}")

    # -- memory & sessions -------------------------------------------------------------------------

    async def _find_memory(self, api: Api, scope: str, item_title: str) -> dict[str, Any] | None:
        for status in (None, "forgotten"):
            for item in await api.pages(f"{self.base}/memory", scope=scope, status=status):
                if item.get("title") == item_title:
                    return item
        return None

    async def seed_memory(self) -> None:
        title("Mémoire (en plus de l'extraction automatique)")
        owner = await self.as_user(self.manifest["project"]["owner"])
        org_items = [item for item in self.manifest["memory"] if item.get("org")]
        if org_items and await self.db():
            from app.seed.direct import ensure_org_memory

            created, kept = await ensure_org_memory(org_items, self.admin_email)
            say(f"  ✓ mémoire long terme d'organisation : {created} créée(s), {kept} existante(s)")
        for item in self.manifest["memory"]:
            if item.get("org"):
                continue
            await self.optional(f"Mémoire {item['key']}", self._seed_memory_item(owner, item))

    async def _seed_memory_item(self, owner: Api, item: dict[str, Any]) -> None:
        author = (
            self.agent_api(item["as_agent"]) if item.get("as_agent") else await self.as_user(item["as_user"])
        )
        lookup = author if item["scope"] == "user" else owner
        found = await self._find_memory(lookup, item["scope"], item["title"])
        if found is None:
            body: dict[str, Any] = {
                "scope": item["scope"],
                "kind": item["kind"],
                "title": item["title"],
                "content": item["content"],
                "tags": item.get("tags", []),
            }
            if item.get("status"):
                body["status"] = item["status"]
            if item.get("subject"):
                body["subject_user_id"] = self.user_id(item["subject"])
            if item.get("session_id"):
                body["session_id"] = item["session_id"]
            found = await author.post(f"{self.base}/memory", body)
            say(
                f"  + [{item['scope']}/{item['kind']}] {item['title']} "
                f"({found.get('status')}, par {author.label})"
            )
        else:
            say(f"  = [{item['scope']}/{item['kind']}] {item['title']} (existant, {found.get('status')})")
        forget = item.get("forget")
        if forget and found.get("status") != "forgotten":
            forgetter = await self.as_user(forget["as_user"])
            await forgetter.post(f"{self.base}/memory/{found['id']}/forget", {"reason": forget["reason"]})
            say(f"    ✓ oubli sélectif : « {forget['reason']} »")

    async def seed_sessions(self) -> None:
        title("Mémoire court terme (sessions)")
        owner = await self.as_user(self.manifest["project"]["owner"])
        existing = {s["session_id"] for s in await owner.get(f"{self.base}/sessions")}
        for session in self.manifest["sessions"]:
            sid = session["id"]
            if sid in existing:
                say(f"  = {sid} (existante)")
            else:
                agent = self.agent_api(session["agent"])
                count = 0
                for turn in session["turns"]:
                    result = await agent.post(
                        f"{self.base}/sessions/{sid}/turns",
                        {"role": turn["role"], "content": turn["content"]},
                    )
                    count = int(result.get("turns", count + 1))
                say(f"  + {sid} : {count} tour(s) par {agent.label}")
            if session.get("expire"):
                if await self.db():
                    from app.seed.direct import expire_session

                    expired = await expire_session(self.slug, sid)
                    say(f"    ✓ session expirée de force ({expired} item(s) court terme expirés)")
                else:
                    self.warn(f"Session {sid} non expirée (accès base requis)")

    # -- usage history -----------------------------------------------------------------------------

    async def replay_context_history(self) -> None:
        title("Historique d'utilisation (requêtes de contexte réelles)")
        owner = await self.as_user(self.manifest["project"]["owner"])
        requests = self.manifest["context_requests"]
        already = await owner.total(f"{self.base}/context/requests")
        if already >= len(requests) and not self.reset:
            say(
                f"  = {already} requêtes déjà présentes : historique conservé "
                "(utilisez --reset pour le rejouer)"
            )
            return
        for index, spec in enumerate(requests, start=1):
            await self.optional(f"Requête {index}", self._run_request(index, spec))

    async def _run_request(self, index: int, spec: dict[str, Any]) -> None:
        body: dict[str, Any] = {"task": spec["task"]}
        for key in ("intent", "token_budget", "session_id"):
            if spec.get(key) is not None:
                body[key] = spec[key]
        if spec.get("base_snapshot"):
            base = dict(spec["base_snapshot"])
            base["version"] = self.saved_snapshots.get(base["name"], base.get("version"))
            body["base_snapshot"] = {k: v for k, v in base.items() if v is not None}
        if spec.get("save_snapshot"):
            body["save_snapshot"] = {"name": spec["save_snapshot"]}
        if spec["via"] == "agent":
            api = self.agent_api(spec["agent"])
            body["on_behalf_of"] = self.user_id(spec["user"])
        else:
            api = await self.as_user(spec["user"])
            body["agent_id"] = str(self.agents[spec["agent"]]["id"])
            body["explain"] = True
        package = await api.post(f"{self.base}/context", body)
        snapshot = package.get("snapshot")
        if snapshot:
            self.saved_snapshots[snapshot["name"]] = int(snapshot["version"])
        minute = (index * 17) % 60
        result = RequestResult(
            index=index,
            spec=spec,
            request_id=uuid.UUID(str(package["request_id"])),
            created_at=mf.day_at(self.now, int(spec["day_offset"]), int(spec["hour"]), minute),
            exclusion_summary={k: int(v) for k, v in (package.get("exclusion_summary") or {}).items()},
            included=len(package.get("items") or []),
            tokens=int(package.get("tokens_used") or 0),
            snapshot=snapshot,
        )
        self.results.append(result)
        excluded = sum(result.exclusion_summary.values())
        snap = f" → snapshot {snapshot['name']} v{snapshot['version']}" if snapshot else ""
        say(
            f"  {index:>2}. {api.label:<18} {spec['task'][:58]:<58} "
            f"{result.included:>2} retenus / {excluded:>2} exclus · {result.tokens} tokens{snap}"
        )
        feedback = spec.get("feedback")
        if feedback:
            await self.optional(f"Feedback requête {index}", self._send_feedback(api, package, feedback))

    async def _send_feedback(self, api: Api, package: dict[str, Any], feedback: dict[str, Any]) -> None:
        body: dict[str, Any] = {"rating": int(feedback["rating"])}
        if feedback.get("comment"):
            body["comment"] = feedback["comment"]
        if feedback.get("flag_outdated"):
            dated = [i for i in package.get("items") or [] if i.get("citation") and i.get("date")]
            if dated:
                oldest = min(dated, key=lambda i: str(i["date"]))
                body["item_flags"] = [{"citation": oldest["citation"], "flag": "outdated"}]
        await api.post(f"{self.base}/context/requests/{package['request_id']}/feedback", body)
        self.stats["feedback"] += 1

    async def redistribute_timestamps(self) -> None:
        if not self.results:
            return
        title("Redistribution des horodatages (données de démonstration)")
        if not await self.db():
            self.warn(
                "Horodatages non redistribués (accès base requis) : toutes les requêtes datent d'aujourd'hui"
            )
            return
        from app.seed.direct import TimestampPlan, redistribute

        plan = [TimestampPlan(r.request_id, r.created_at) for r in self.results]
        moved = await redistribute(plan)
        days = sorted({r.created_at.date() for r in self.results})
        say(
            f"  ✓ {moved} requêtes (et leurs snapshots, feedbacks, audit) réparties du {days[0]:%d/%m} au "
            f"{days[-1]:%d/%m} — DONNÉES DE DÉMONSTRATION"
        )

    # -- summary -----------------------------------------------------------------------------------

    async def print_summary(self) -> None:
        title("Résumé")
        owner = await self.as_user(self.manifest["project"]["owner"])
        rows: list[tuple[str, str]] = [
            ("Utilisateurs démo", str(len(self.users))),
            ("Sources", str(len(self.sources))),
        ]
        doc_counts = {s: await owner.total(f"{self.base}/documents", status=s) for s in DOCUMENT_STATUSES}
        rows.append(("Documents", f"{sum(doc_counts.values())} ({self._fmt(doc_counts)})"))
        mem_counts = {s: await owner.total(f"{self.base}/memory", status=s) for s in MEMORY_STATUSES}
        rows.append(("Mémoire (visible de Camille)", f"{sum(mem_counts.values())} ({self._fmt(mem_counts)})"))
        rows.append(("Sessions actives", str(len(await owner.get(f"{self.base}/sessions")))))
        rows.append(("Requêtes de contexte", str(await owner.total(f"{self.base}/context/requests"))))
        snapshots = await owner.get(f"{self.base}/snapshots")
        rows.append(
            ("Snapshots", ", ".join(f"{s['name']} v{s['latest_version']}" for s in snapshots) or "aucun")
        )
        rows.append(("Feedbacks envoyés", str(self.stats["feedback"])))
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            say(f"  {label:<{width}}  {value}")

        if self.results:
            reasons: Counter[str] = Counter()
            for result in self.results:
                reasons.update(result.exclusion_summary)
            included = sum(r.included for r in self.results)
            say()
            say(f"  {'Codes de raison (requêtes du seed)':<40} {'Nombre':>6}")
            say(f"  {'INCLUDED (retenus)':<40} {included:>6}")
            for code, count in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
                say(f"  {code:<40} {count:>6}")

        say()
        say(f"  Comptes de démonstration (mot de passe : {self.manifest['demo_password']}) :")
        for user in self.manifest["users"]:
            say(f"    {user['email']:<34} {user['role']:<7} C{user['clearance']}  {user['full_name']}")
        say(f"    {self.admin_email:<34} admin   C3  (mot de passe administrateur)")
        say(f"  Clés d'agents : {AGENTS_FILE}")
        if self.warnings:
            say()
            say(f"  {len(self.warnings)} avertissement(s) :")
            for warning in self.warnings:
                say(f"    - {warning}")

    @staticmethod
    def _fmt(counts: dict[str, int]) -> str:
        return ", ".join(f"{k} {v}" for k, v in counts.items() if v) or "aucun"


# --------------------------------------------------------------------------------------------------
# CLI


def _settings_default(name: str, fallback: str) -> str:
    try:
        from app.config import settings

        return str(getattr(settings, name)) or fallback
    except Exception:
        return fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description="Charge le projet de démonstration « Atlas » (données fictives) via l'API ORBIT.",
    )
    parser.add_argument("--api", default=DEFAULT_API, help="URL de l'API (défaut : %(default)s)")
    parser.add_argument(
        "--reset", action="store_true", help="supprime le projet atlas et les utilisateurs démo avant"
    )
    parser.add_argument(
        "--admin-email",
        default=_settings_default("bootstrap_admin_email", "admin@orbit.local"),
        help="compte admin",
    )
    parser.add_argument(
        "--admin-password",
        default=_settings_default("bootstrap_admin_password", "orbit-admin"),
        help="mot de passe",
    )
    parser.add_argument(
        "--jobs-timeout", type=float, default=900.0, help="attente max du worker par phase (s)"
    )
    parser.add_argument("--no-history", action="store_true", help="ne rejoue pas les requêtes de contexte")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seeder = Seeder(
        api_url=args.api,
        admin_email=args.admin_email,
        admin_password=args.admin_password,
        reset=args.reset,
        jobs_timeout=args.jobs_timeout,
        replay_history=not args.no_history,
    )
    try:
        return asyncio.run(seeder.run())
    except (SeedAbort, ApiError) as exc:
        say(f"\n✗ Seed interrompu : {exc}")
        return 1
    except KeyboardInterrupt:
        say("\n✗ Seed interrompu par l'utilisateur")
        return 130


if __name__ == "__main__":
    sys.exit(main())
