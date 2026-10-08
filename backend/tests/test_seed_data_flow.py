"""End-to-end run of the demo seed against an in-memory fake of the REST API (no database needed).

The fake implements just enough of docs/API.md (auth, users, projects, members, agents, sources,
documents, jobs, memory, sessions, context, snapshots) to check the orchestration: order of phases,
versioning of the specification, validations, forgetting, snapshots derived from ``spec-atlas@v2``,
feedback, and idempotency of a second run. Database-only steps are disabled.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections import Counter
from email.parser import BytesParser
from email.policy import default as email_policy
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.seed import seed as seed_module
from app.seed.seed import Seeder

ADMIN = ("admin@orbit.local", "orbit-admin")


def _page(items: list[dict[str, Any]], query: dict[str, str]) -> dict[str, Any]:
    page, size = int(query.get("page", 1)), int(query.get("page_size", 25))
    return {
        "items": items[(page - 1) * size : page * size],
        "total": len(items),
        "page": page,
        "page_size": size,
    }


class FakeOrbit:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {
            "admin@orbit.local": {
                "id": str(uuid.uuid4()),
                "email": ADMIN[0],
                "full_name": "Admin",
                "clearance": 3,
            }
        }
        self.passwords = {ADMIN[0]: ADMIN[1]}
        self.project: dict[str, Any] | None = None
        self.members: dict[str, str] = {}
        self.agents: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, str] = {}
        self.sources: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self.memory: list[dict[str, Any]] = []
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[dict[str, Any]] = []
        self.snapshots: dict[str, int] = {}
        self.queued = 0
        self.calls: Counter[str] = Counter()
        self.feedback: list[dict[str, Any]] = []

    # -- identity ---------------------------------------------------------------------------------

    def _caller(self, request: httpx.Request) -> tuple[str, dict[str, Any]]:
        key = request.headers.get("x-orbit-key")
        if key:
            return "agent", self.agents[self.keys[key]]
        cookie = request.headers.get("cookie", "")
        email = cookie.split("orbit_session=")[-1].split(";")[0]
        return "user", self.users[email]

    # -- helpers ----------------------------------------------------------------------------------

    def _extract_memory(self, doc: dict[str, Any], content: str) -> None:
        for line in content.splitlines():
            for marker, kind in (("Décision :", "decision"), ("Contrainte :", "constraint")):
                if marker in line:
                    self._new_memory(kind, line.split(marker, 1)[1].strip(), "proposed")
            if "compte 650 postes" in line:
                self._new_memory("fact", line.strip(), "proposed")

    def _new_memory(self, kind: str, text: str, status: str, **extra: Any) -> dict[str, Any]:
        item = {"id": str(uuid.uuid4()), "scope": "project", "kind": kind, "status": status}
        item.update({"title": text[:120], "content": text, **extra})
        self.memory.append(item)
        return item

    def _add_document(self, source_id: str, external_id: str | None, title: str) -> dict[str, Any]:
        for doc in self.documents:
            if doc["source_id"] == source_id and external_id and doc["external_id"] == external_id:
                doc["current_version"] += 1
                return doc
        doc = {"id": str(uuid.uuid4()), "source_id": source_id, "external_id": external_id, "title": title}
        doc.update({"current_version": 1, "status": "indexed"})
        self.documents.append(doc)
        return doc

    # -- router -----------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        path = url.path.removeprefix("/api/v1")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        method = request.method
        self.calls[f"{method} {path.split('/')[1] if path.count('/') else path}"] += 1
        body: Any = None
        if request.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(request.content)

        def ok(data: Any, status: int = 200, **kw: Any) -> httpx.Response:
            return httpx.Response(status, json=data, **kw)

        if path == "/auth/login":
            if self.passwords.get(body["email"]) != body["password"]:
                return ok({"detail": "Identifiants invalides", "code": "unauthorized"}, 401)
            return ok(
                self.users[body["email"]], headers={"set-cookie": f"orbit_session={body['email']}; Path=/"}
            )
        kind, caller = self._caller(request)
        if path == "/auth/me":
            return ok(caller)
        if path == "/users" and method == "GET":
            return ok([u for u in self.users.values() if query.get("q", "") in u["email"]])
        if path == "/users" and method == "POST":
            user = {"id": str(uuid.uuid4()), **{k: body[k] for k in ("email", "full_name", "clearance")}}
            self.users[body["email"]] = user
            self.passwords[body["email"]] = body["password"]
            return ok(user, 201)
        if path.startswith("/users/") and method == "PATCH":
            user = next(u for u in self.users.values() if u["id"] == path.split("/")[2])
            user.update({k: v for k, v in body.items() if k != "password"})
            if "password" in body:
                self.passwords[user["email"]] = body["password"]
            return ok(user)
        if path == "/projects" and method == "POST":
            self.project = {"id": str(uuid.uuid4()), "slug": body["slug"], "name": body["name"]}
            self.members[caller["email"]] = "owner"
            return ok(self.project, 201)

        base = "/projects/atlas"
        if not path.startswith(base):
            return ok({"detail": "introuvable", "code": "not_found"}, 404)
        if self.project is None:
            return ok({"detail": "Projet introuvable", "code": "not_found"}, 404)
        rest = path.removeprefix(base)
        if rest == "":
            return ok(self.project)
        if rest == "/members" and method == "GET":
            return ok([{"user": self.users[e], "role": r} for e, r in self.members.items()])
        if rest == "/members" and method == "POST":
            self.members[body["email"]] = body["role"]
            return ok({"user": self.users[body["email"]], "role": body["role"]}, 201)
        if rest == "/agents" and method == "GET":
            return ok(list(self.agents.values()))
        if (rest == "/agents" and method == "POST") or rest.endswith("/rotate"):
            agent_id = rest.split("/")[2] if rest.endswith("/rotate") else str(uuid.uuid4())
            prefix = uuid.uuid4().hex[:8]
            agent = self.agents.get(agent_id) or {"id": agent_id, "name": body["name"], "active": True}
            agent["api_key_prefix"] = prefix
            self.agents[agent_id] = agent
            key = f"orb_{prefix}_{uuid.uuid4().hex}"
            self.keys = {k: v for k, v in self.keys.items() if v != agent_id} | {key: agent_id}
            return ok({"agent": agent, "api_key": key}, 201)
        if rest == "/sources" and method == "GET":
            return ok(self.sources)
        if rest == "/sources" and method == "POST":
            source = {"id": str(uuid.uuid4()), **body}
            self.sources.append(source)
            return ok(source, 201)
        if rest == "/documents" and method == "GET":
            docs = [d for d in self.documents if query.get("status") in (None, d["status"])]
            return ok(_page(docs, query))
        if rest == "/documents/text":
            doc = self._add_document(body["source_id"], body.get("external_id"), body["title"])
            self._extract_memory(doc, body["content"])
            self.queued += 1
            return ok(doc, 201)
        if rest == "/documents/import":
            ctype = request.headers["content-type"]
            message = BytesParser(policy=email_policy).parsebytes(
                f"Content-Type: {ctype}\r\n\r\n".encode() + request.content
            )
            parts = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
            file_part = parts["file"]
            raw = file_part.get_payload(decode=True).decode()
            source_id = parts["source_id"].get_payload(decode=True).decode()
            if file_part.get_filename().endswith(".csv"):
                records = list(csv.DictReader(io.StringIO(raw)))
            else:
                records = json.loads(raw)
            docs = [
                self._add_document(source_id, r["id"], r.get("title") or r.get("subject") or r["id"])
                for r in records
            ]
            self.queued += 1
            return ok({"created": len(docs), "updated": 0, "documents": docs}, 201)
        if rest == "/jobs":
            total = self.queued if query.get("status") == "queued" else 0
            if query.get("status") == "queued":
                self.queued = 0
            return ok({"items": [], "total": total, "page": 1, "page_size": 1})
        if rest == "/memory" and method == "GET":
            items = [
                m
                for m in self.memory
                if all(query.get(f) in (None, m.get(f)) for f in ("scope", "kind", "status"))
            ]
            return ok(_page(items, query))
        if rest == "/memory" and method == "POST":
            status = "proposed" if kind == "agent" else body.get("status", "proposed")
            extra = {k: body[k] for k in ("subject_user_id", "session_id") if k in body}
            item = self._new_memory(body["kind"], body["content"], status, **extra)
            item.update({"scope": body["scope"], "title": body["title"]})
            return ok(item, 201)
        if rest.startswith("/memory/") and method == "POST":
            _, _, item_id, action = rest.split("/")
            item = next(m for m in self.memory if m["id"] == item_id)
            item["status"] = {"validate": "validated", "forget": "forgotten"}[action]
            self.calls[f"memory.{action}"] += 1
            return ok(item)
        if rest == "/sessions":
            return ok([{"session_id": s, "turns": len(t)} for s, t in self.sessions.items()])
        if rest.startswith("/sessions/") and rest.endswith("/turns"):
            turns = self.sessions.setdefault(rest.split("/")[2], [])
            turns.append(body)
            return ok({"session_id": rest.split("/")[2], "turns": len(turns), "expires_at": None})
        if rest == "/context" and method == "POST":
            base_ref = body.get("base_snapshot")
            if base_ref and self.snapshots.get(base_ref["name"], 0) < base_ref.get("version", 1):
                return ok({"detail": "Snapshot introuvable", "code": "not_found"}, 404)
            assert (kind == "agent") == ("on_behalf_of" in body)
            snapshot = None
            if body.get("save_snapshot"):
                name = body["save_snapshot"]["name"]
                self.snapshots[name] = self.snapshots.get(name, 0) + 1
                snapshot = {"id": str(uuid.uuid4()), "name": name, "version": self.snapshots[name]}
            package = {
                "request_id": str(uuid.uuid4()),
                "items": [
                    {"citation": "S1", "date": "2026-09-20T09:00:00+00:00"},
                    {"citation": "S2", "date": "2025-08-25T09:00:00+00:00"},
                ],
                "exclusion_summary": {"EXCLUDED_STALE": 1, "EXCLUDED_SUPERSEDED": 2},
                "tokens_used": 1200,
                "snapshot": snapshot,
                "body": body,
            }
            self.requests.append(package)
            return ok(package)
        if rest == "/context/requests":
            return ok(_page(self.requests, query))
        if rest.endswith("/feedback"):
            self.feedback.append(body)
            return ok({"id": str(uuid.uuid4())}, 201)
        if rest == "/snapshots":
            return ok([{"name": n, "latest_version": v} for n, v in self.snapshots.items()])
        return ok({"detail": f"non simulé : {method} {rest}", "code": "not_found"}, 404)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> FakeOrbit:
    monkeypatch.setattr(seed_module, "AGENTS_FILE", tmp_path / ".seed-agents.json")

    async def no_db(self: Seeder) -> bool:
        self._db = False
        return False

    monkeypatch.setattr(Seeder, "db", no_db)
    return FakeOrbit()


async def _run(fake: FakeOrbit) -> Seeder:
    seeder = Seeder(
        api_url="http://orbit.test",
        admin_email=ADMIN[0],
        admin_password=ADMIN[1],
        transport=httpx.MockTransport(fake.handle),
        poll_interval=0.0,
    )
    assert await seeder.run() == 0
    return seeder


async def test_seed_runs_the_whole_scenario(fake: FakeOrbit, tmp_path: Any) -> None:
    seeder = await _run(fake)

    assert {e for e in fake.users} >= {u["email"] for u in seeder.manifest["users"]}
    assert fake.members == {u["email"]: u["role"] for u in seeder.manifest["users"]}
    assert len(fake.agents) == 3 and len(fake.sources) == 11
    keys = json.loads((tmp_path / ".seed-agents.json").read_text())["agents"]
    assert set(keys) == {"produit", "design", "engineering"} and all(
        k["api_key"] in fake.keys for k in keys.values()
    )

    assert len(fake.documents) == 12 + 5 + 8 + 3 + 12  # records + text documents (spec = 1 document)
    spec = next(d for d in fake.documents if d["external_id"] == "spec-fonctionnelle-atlas")
    assert spec["current_version"] == 2

    statuses = Counter((m["kind"], m["status"]) for m in fake.memory)
    assert statuses[("decision", "validated")] >= 5
    assert statuses[("fact", "validated")] == 1
    assert fake.calls["memory.forget"] == 1
    assert (
        next(m for m in fake.memory if m["title"] == "Le prestataire Deskora a été retenu")["status"]
        == "forgotten"
    )
    prefs = [m for m in fake.memory if m["kind"] == "preference"]
    assert len(prefs) == 2 and all(m["status"] == "validated" and m.get("subject_user_id") for m in prefs)
    assert len(fake.sessions["atlas-spec-redaction"]) == 4

    assert len(fake.requests) == len(seeder.manifest["context_requests"]) == len(seeder.results)
    assert fake.snapshots == {"spec-atlas": 2, "design-atlas": 1, "archi-atlas": 1}
    derived = [r["body"] for r in fake.requests if r["body"].get("base_snapshot")]
    assert all(b["base_snapshot"] == {"name": "spec-atlas", "version": 2} for b in derived)
    explorer = [r["body"] for r in fake.requests if "agent_id" in r["body"]]
    assert explorer and all(b["explain"] is True for b in explorer)
    assert len(fake.feedback) == sum(1 for r in seeder.manifest["context_requests"] if r.get("feedback"))
    flagged = [f for f in fake.feedback if f.get("item_flags")]
    assert flagged == [
        {
            "rating": 3,
            "comment": "Le benchmark de veille n'est plus d'actualité.",
            "item_flags": [{"citation": "S2", "flag": "outdated"}],
        }
    ]
    assert all(r.created_at < seeder.now for r in seeder.results)
    assert len({r.created_at.date() for r in seeder.results}) == 14


async def test_seed_is_idempotent(fake: FakeOrbit) -> None:
    await _run(fake)
    counts = (len(fake.users), len(fake.documents), len(fake.memory), len(fake.requests), len(fake.sources))
    await _run(fake)
    assert (
        len(fake.users),
        len(fake.documents),
        len(fake.memory),
        len(fake.requests),
        len(fake.sources),
    ) == counts
    assert fake.snapshots == {"spec-atlas": 2, "design-atlas": 1, "archi-atlas": 1}
    assert fake.calls["memory.forget"] == 1
