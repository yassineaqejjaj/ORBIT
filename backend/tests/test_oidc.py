"""OIDC relying party (NOV-109): signed fixture tokens of ``contracts/claims`` (NOVA), a fake IdP, no network.

The IdP is an ``httpx.MockTransport`` (discovery, JWKS, token endpoint with a real PKCE check) and the clock is
pinned to the instant the fixtures were signed for. With ``ORBIT_OIDC_ENABLED`` off (default) nothing changes.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.config import settings
from app.db import get_sessionmaker
from app.models import AuditLog, ExternalIdentity, Project, ProjectMember, User, Workspace
from app.services import oidc
from app.services.users import create_user
from tests.conftest import DEFAULT_PASSWORD
from tests.test_claims_contract import CASES, CONTEXT, JWKS

ISSUER = CONTEXT["issuer"]
WORKSPACE = CASES["standard_user"]["claims"]["orion_workspace_id"]
PROJECT = CASES["standard_user"]["claims"]["orion_project_id"]
SUBJECT = CASES["standard_user"]["claims"]["sub"]
EMAIL = CASES["standard_user"]["claims"]["email"]
OTHER_WORKSPACE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def token_of(case: str) -> str:
    return str(CASES[case]["tokens"]["orbit"])


class FakeIdP:
    """Discovery + JWKS + token endpoint. ``access_token`` is what the token endpoint will return."""

    def __init__(self) -> None:
        self.jwks: dict[str, Any] = JWKS
        self.access_token = token_of("standard_user")
        self.challenge: str | None = None
        self.requests: list[str] = []
        self.down = False
        self.code_valid = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.down:
            return httpx.Response(503)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
                },
            )
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json=self.jwks)
        if request.url.path.endswith("/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            digest = hashlib.sha256(form["code_verifier"].encode()).digest()
            challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            if (
                not self.code_valid
                or challenge != self.challenge
                or form["grant_type"] != "authorization_code"
            ):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": self.access_token, "token_type": "Bearer"})
        return httpx.Response(404)

    def count(self, suffix: str) -> int:
        return sum(1 for path in self.requests if path.endswith(suffix))


@pytest.fixture
def idp(monkeypatch: pytest.MonkeyPatch) -> FakeIdP:
    fake = FakeIdP()
    monkeypatch.setattr(settings, "oidc_enabled", True)
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_audience", "orbit")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://orbit.example.test/api/v1/auth/oidc/callback")
    monkeypatch.setattr(oidc, "transport_override", httpx.MockTransport(fake))
    monkeypatch.setattr(oidc, "clock_override", float(CONTEXT["now"]))
    oidc.reset_cache()
    oidc._link_attempts.clear()
    return fake


@pytest_asyncio.fixture
async def world() -> AsyncIterator[Callable[..., Any]]:
    """Factory: workspace A, Alice (matching the fixtures' e-mail), a project named by the token and another one."""

    async def build(*, admin: bool = False, workspace: str = WORKSPACE, clearance: int = 3) -> dict[str, Any]:
        async with get_sessionmaker()() as session:
            await session.execute(delete(ExternalIdentity).where(ExternalIdentity.issuer == ISSUER))
            await session.execute(delete(User).where(User.email == EMAIL))
            await session.execute(delete(Project).where(Project.orion_project_id == uuid.UUID(PROJECT)))
            for ws in {WORKSPACE, workspace, OTHER_WORKSPACE}:
                if await session.get(Workspace, uuid.UUID(ws)) is None:
                    session.add(Workspace(id=uuid.UUID(ws), name=f"Espace {ws[:4]}"))
            await session.flush()
            alice = await create_user(
                session,
                email=EMAIL,
                full_name="Alice Example",
                password=DEFAULT_PASSWORD,
                clearance=clearance,
                is_admin=admin,
                workspace_id=uuid.UUID(workspace),
            )
            named = Project(
                slug=f"oidc-{uuid.uuid4().hex[:8]}",
                name="Projet nommé par le jeton",
                workspace_id=uuid.UUID(WORKSPACE),
                orion_project_id=uuid.UUID(PROJECT),
            )
            other = Project(
                slug=f"oidc-{uuid.uuid4().hex[:8]}", name="Autre projet", workspace_id=uuid.UUID(WORKSPACE)
            )
            session.add_all([named, other])
            await session.flush()
            session.add_all(
                [
                    ProjectMember(project_id=named.id, user_id=alice.id, role="editor"),
                    ProjectMember(project_id=other.id, user_id=alice.id, role="editor"),
                ]
            )
            await session.commit()
            return {"user": alice.id, "named": named.slug, "other": other.slug}

    yield build
    async with get_sessionmaker()() as session:
        await session.execute(delete(ExternalIdentity).where(ExternalIdentity.issuer == ISSUER))
        await session.execute(delete(User).where(User.email == EMAIL))
        await session.execute(delete(Project).where(Project.orion_project_id == uuid.UUID(PROJECT)))
        await session.commit()


async def link_alice(user_id: uuid.UUID, *, workspace: str = WORKSPACE, subject: str = SUBJECT) -> None:
    async with get_sessionmaker()() as session:
        session.add(
            ExternalIdentity(
                user_id=user_id,
                workspace_id=uuid.UUID(workspace),
                issuer=ISSUER,
                subject=subject,
                email=EMAIL,
                linked_by="confirmed",
            )
        )
        await session.commit()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def identities() -> list[ExternalIdentity]:
    async with get_sessionmaker()() as session:
        return list(await session.scalars(select(ExternalIdentity).where(ExternalIdentity.issuer == ISSUER)))


async def audit_actions() -> set[str]:
    async with get_sessionmaker()() as session:
        rows = await session.scalars(select(AuditLog.action).where(AuditLog.action.like("auth.sso_%")))
        return set(rows)


async def start_flow(client: httpx.AsyncClient, idp: FakeIdP) -> str:
    """GET /auth/oidc/login, check the redirect, register the PKCE challenge in the fake IdP; returns ``state``."""
    response = await client.get("/api/v1/auth/oidc/login")
    assert response.status_code == 302, response.text
    target = urlparse(response.headers["location"])
    query = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert f"{target.scheme}://{target.netloc}{target.path}" == f"{ISSUER}/protocol/openid-connect/auth"
    assert query["response_type"] == "code" and query["code_challenge_method"] == "S256"
    assert query["client_id"] == "orbit" and query["state"] and query["nonce"] and query["code_challenge"]
    assert query["redirect_uri"] == settings.oidc_redirect_uri
    idp.challenge = query["code_challenge"]
    return query["state"]


# --- Disabled by default ------------------------------------------------------------------------------------------


async def test_everything_is_inert_by_default(client: httpx.AsyncClient, world: Callable[..., Any]) -> None:
    assert settings.oidc_enabled is False
    ids = await world()
    for method, path in (
        ("GET", "/api/v1/auth/oidc/login"),
        ("GET", "/api/v1/auth/oidc/callback"),
        ("POST", "/api/v1/auth/oidc/link/confirm"),
    ):
        assert (await client.request(method, path)).status_code in (404, 422)
    await link_alice(ids["user"])
    garbage = await client.get("/api/v1/projects", headers=bearer("not-a-token"))
    rs256 = await client.get("/api/v1/projects", headers=bearer(token_of("standard_user")))
    assert garbage.status_code == rs256.status_code == 401  # an IdP token is just an unknown token
    assert garbage.json()["detail"] == rs256.json()["detail"]
    assert (
        await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": DEFAULT_PASSWORD})
    ).status_code == 200


def test_enabling_oidc_requires_an_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    with pytest.raises(ValueError, match="ORBIT_OIDC_ISSUER"):
        Settings(oidc_enabled=True, oidc_issuer="")
    assert Settings(oidc_enabled=False).oidc_enabled is False


# --- Bearer tokens ------------------------------------------------------------------------------------------------


async def test_a_linked_token_authenticates_the_local_account_and_narrows_it(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    ids = await world()
    await link_alice(ids["user"])
    # standard_user: orion_project_id = the named project, orion_clearance 2 (local 3), no orbit-admin
    listed = await client.get("/api/v1/projects", headers=bearer(token_of("standard_user")))
    assert listed.status_code == 200
    assert {p["slug"] for p in listed.json()} >= {ids["named"], ids["other"]}  # the list is membership based
    ok = await client.get(
        f"/api/v1/_test/projects/{ids['named']}/viewer", headers=bearer(token_of("standard_user"))
    )
    assert ok.status_code == 200
    assert ok.json()["clearance"] == 2  # min(local 3, orion_clearance 2)
    assert ok.json()["role"] == "editor"  # the local membership, never a realm role
    other = await client.get(
        f"/api/v1/_test/projects/{ids['other']}/viewer", headers=bearer(token_of("standard_user"))
    )
    assert other.status_code == 404  # a token that names a project opens that project only
    # without a project in the token the membership decides
    open_token = bearer(token_of("workspace_without_project"))
    assert (
        await client.get(f"/api/v1/_test/projects/{ids['other']}/viewer", headers=open_token)
    ).status_code == 200
    # the password session of the same account keeps its full local clearance
    await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": DEFAULT_PASSWORD})
    local = await client.get(f"/api/v1/_test/projects/{ids['other']}/viewer")
    assert local.json()["clearance"] == 3


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("expired", 401),
        ("expires_now", 401),
        ("not_yet_valid", 401),
        ("wrong_issuer", 401),
        ("wrong_audience", 401),
        ("bad_signature", 401),
        ("tampered_payload", 401),
        ("alg_none", 401),
        ("alg_hs256", 401),
        ("missing_subject", 401),
        ("clearance_malformed", 401),
        ("clearance_out_of_range", 401),
        ("invalid_workspace_id", 401),
        ("delegated_too_long", 401),
        ("no_workspace", 403),
        ("project_without_workspace", 403),
        ("service_account", 403),
    ],
)
async def test_invalid_or_unusable_tokens_are_refused(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP, case: str, status: int
) -> None:
    ids = await world()
    await link_alice(ids["user"])
    response = await client.get("/api/v1/projects", headers=bearer(token_of(case)))
    assert response.status_code == status, (case, response.text)


async def test_a_token_whose_workspace_is_not_the_accounts_is_refused(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    ids = await world(workspace=OTHER_WORKSPACE)  # Alice lives in another workspace than the token's
    await link_alice(ids["user"], workspace=OTHER_WORKSPACE)
    assert (
        await client.get("/api/v1/projects", headers=bearer(token_of("standard_user")))
    ).status_code == 403


async def test_an_unlinked_subject_is_not_an_account(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    await world()
    response = await client.get("/api/v1/projects", headers=bearer(token_of("standard_user")))
    assert response.status_code == 401 and "non lié" in response.json()["detail"]
    assert await identities() == []  # a request never creates a link


async def test_the_token_clock_is_enforced_after_expiry(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await world()
    await link_alice(ids["user"])
    assert (
        await client.get("/api/v1/projects", headers=bearer(token_of("standard_user")))
    ).status_code == 200
    monkeypatch.setattr(oidc, "clock_override", float(CASES["standard_user"]["claims"]["exp"]) + 1)
    response = await client.get("/api/v1/projects", headers=bearer(token_of("standard_user")))
    assert response.status_code == 401  # a user disabled in the IdP loses access when the token expires


async def test_orbit_admin_counts_only_for_a_local_administrator(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    admin_token, user_token = bearer(token_of("administrator")), bearer(token_of("standard_user"))
    ids = await world(admin=False)
    await link_alice(ids["user"])
    assert (await client.get("/api/v1/users", headers=admin_token)).status_code == 403  # realm role alone: no
    ids = await world(admin=True)
    await link_alice(ids["user"])
    assert (await client.get("/api/v1/users", headers=admin_token)).status_code == 200  # both: yes
    assert (await client.get("/api/v1/users", headers=user_token)).status_code == 403  # local flag alone: no


async def test_the_jwks_is_cached_and_refetched_on_an_unknown_key(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    ids = await world()
    await link_alice(ids["user"])
    headers = bearer(token_of("standard_user"))
    idp.jwks = {"keys": []}  # the IdP rotated: the cached set does not know our kid yet
    oidc.reset_cache()
    assert (
        await client.get("/api/v1/projects", headers=headers)
    ).status_code == 401  # nothing known, refetch fails
    idp.jwks = JWKS
    oidc.clock_override = float(CONTEXT["now"]) + 31  # past the refetch rate limit (pinned clock)
    oidc.reset_cache()
    first = idp.count("/certs")
    assert (await client.get("/api/v1/projects", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/projects", headers=headers)).status_code == 200
    assert idp.count("/certs") == first + 1  # cached: one fetch for two requests


async def test_a_key_rotation_needs_no_restart(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    ids = await world()
    await link_alice(ids["user"])
    headers = bearer(token_of("standard_user"))
    stale = {"keys": [{**JWKS["keys"][0], "kid": "some-old-key"}]}
    idp.jwks = stale
    assert (await client.get("/api/v1/projects", headers=headers)).status_code == 401
    idp.jwks = JWKS  # the new key is published; the next unknown-kid request refetches
    oidc._cache.forced_at = 0.0
    assert (await client.get("/api/v1/projects", headers=headers)).status_code == 200


async def test_an_unreachable_idp_is_a_503_not_an_open_door(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    ids = await world()
    await link_alice(ids["user"])
    idp.down = True
    assert (
        await client.get("/api/v1/projects", headers=bearer(token_of("standard_user")))
    ).status_code == 503


# --- Browser flow and confirmed linking ---------------------------------------------------------------------------


async def test_the_browser_flow_links_only_after_the_user_confirms(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    await world()
    state = await start_flow(client, idp)
    callback = await client.get("/api/v1/auth/oidc/callback", params={"code": "c1", "state": state})
    assert callback.status_code == 202, callback.text
    body = callback.json()
    assert body["status"] == "link_required" and body["email"] == "a***@example.test"
    assert "orbit_session" not in callback.cookies and await identities() == []  # nothing linked, no session

    # the link token is not a session
    assert (await client.get("/api/v1/auth/me", headers=bearer(body["link_token"]))).status_code == 401
    wrong = await client.post(
        "/api/v1/auth/oidc/link/confirm",
        json={"link_token": body["link_token"], "password": "mauvais-mot-de-passe"},
    )
    assert wrong.status_code == 401 and await identities() == []  # refused: still nothing

    confirmed = await client.post(
        "/api/v1/auth/oidc/link/confirm",
        json={"link_token": body["link_token"], "password": DEFAULT_PASSWORD},
    )
    assert confirmed.status_code == 200 and confirmed.json()["email"] == EMAIL
    assert "orbit_session" in confirmed.cookies
    [identity] = await identities()
    assert (identity.subject, identity.linked_by) == (SUBJECT, "confirmed")
    assert str(identity.workspace_id) == WORKSPACE

    # next time the subject is known: straight to a session, no confirmation
    state = await start_flow(client, idp)
    again = await client.get("/api/v1/auth/oidc/callback", params={"code": "c2", "state": state})
    assert again.status_code == 200 and again.json()["email"] == EMAIL
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert {"auth.sso_link", "auth.sso_login", "auth.sso_refused"} <= await audit_actions()


async def test_the_flow_rejects_a_forged_state_a_bad_code_and_a_replayed_callback(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    await world()
    state = await start_flow(client, idp)
    assert (
        await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": "forged"})
    ).status_code == 401
    idp.code_valid = False
    assert (
        await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    ).status_code == 401
    idp.code_valid = True
    ok = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    assert ok.status_code == 202
    replay = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    assert replay.status_code == 401  # the flow cookie was consumed
    anonymous = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")
    async with anonymous:
        assert (
            await anonymous.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
        ).status_code == 401


async def test_an_unverified_email_or_no_matching_account_links_nothing_and_creates_nothing(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    await world()
    idp.access_token = token_of("email_unverified")
    state = await start_flow(client, idp)
    refused = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    assert (
        refused.status_code == 403 and await identities() == []
    )  # a verified e-mail is required to even ask

    async with get_sessionmaker()() as session:  # no local account at all, auto-provisioning off (default)
        await session.execute(delete(User).where(User.email == EMAIL))
        await session.commit()
    idp.access_token = token_of("standard_user")
    state = await start_flow(client, idp)
    assert (
        await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    ).status_code == 403
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(User.id).where(User.email == EMAIL)) is None  # nothing created


async def test_a_matching_email_in_another_workspace_is_not_a_candidate(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    await world(workspace=OTHER_WORKSPACE)
    state = await start_flow(client, idp)
    assert (
        await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    ).status_code == 403


async def test_the_link_token_burns_after_a_few_wrong_passwords(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    await world()
    state = await start_flow(client, idp)
    token = (await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})).json()[
        "link_token"
    ]
    codes = [
        (
            await client.post(
                "/api/v1/auth/oidc/link/confirm", json={"link_token": token, "password": "faux-faux"}
            )
        ).status_code
        for _ in range(oidc.MAX_LINK_ATTEMPTS + 1)
    ]
    assert codes[: oidc.MAX_LINK_ATTEMPTS] == [401] * oidc.MAX_LINK_ATTEMPTS and codes[-1] == 403
    right = await client.post(
        "/api/v1/auth/oidc/link/confirm", json={"link_token": token, "password": DEFAULT_PASSWORD}
    )
    assert right.status_code == 403 and await identities() == []


async def test_auto_provision_is_opt_in_and_creates_a_minimal_account(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP, monkeypatch: pytest.MonkeyPatch
) -> None:
    await world()
    async with get_sessionmaker()() as session:
        await session.execute(delete(User).where(User.email == EMAIL))
        await session.commit()
    monkeypatch.setattr(settings, "oidc_auto_provision", True)
    idp.access_token = token_of("email_unverified")  # an unverified e-mail never provisions
    state = await start_flow(client, idp)
    assert (
        await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    ).status_code == 403
    idp.access_token = token_of("administrator")  # even a token carrying orbit-admin creates a plain account
    state = await start_flow(client, idp)
    created = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    assert created.status_code == 200, created.text
    assert created.json()["is_admin"] is False and created.json()["clearance"] == 1
    [identity] = await identities()
    assert identity.linked_by == "auto_provision" and str(identity.workspace_id) == WORKSPACE


async def test_unlinking_removes_the_sso_access_but_not_the_account(
    client: httpx.AsyncClient, world: Callable[..., Any], idp: FakeIdP
) -> None:
    ids = await world()
    await link_alice(ids["user"])
    headers = bearer(token_of("standard_user"))
    assert (await client.get("/api/v1/auth/oidc/identity", headers=headers)).json()[0][
        "linked_by"
    ] == "confirmed"
    assert (await client.delete("/api/v1/auth/oidc/identity", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/projects", headers=headers)).status_code == 401
    assert (
        await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": DEFAULT_PASSWORD})
    ).status_code == 200


# --- Double stack ---------------------------------------------------------------------------------------------------


async def test_passwords_sessions_and_agent_keys_work_unchanged_with_oidc_on(
    client: httpx.AsyncClient,
    admin_client: httpx.AsyncClient,
    project: dict[str, object],
    idp: FakeIdP,
    agent_client: Callable[..., httpx.AsyncClient],
) -> None:
    slug = project["slug"]
    assert (await admin_client.get(f"/api/v1/projects/{slug}")).status_code == 200  # session cookie
    created = await admin_client.post(
        f"/api/v1/projects/{slug}/agents", json={"name": "agent-oidc", "kind": "engineering", "clearance": 1}
    )
    key = created.json()["api_key"]
    keyed = agent_client(key)
    assert (await keyed.get("/api/v1/agents/self")).status_code == 200  # orb_ key, same contract
    assert (await keyed.post(f"/api/v1/projects/{slug}/context", json={"task": "bonjour"})).status_code == 200
    assert (
        await client.get("/api/v1/projects", headers=bearer(key))
    ).status_code == 403  # a key is not a user
    assert not [p for p in idp.requests if p.endswith("/certs")]  # session and key paths never call the IdP
