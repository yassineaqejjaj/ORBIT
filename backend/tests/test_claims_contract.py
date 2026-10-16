"""ORION claims contract (NOV-104): the table of ADR 001 §4 executed on the signed fixtures of ``contracts/claims``.

PORTABLE (ORBIT copy, NOV-109; SERVICES and the module path edited once): this file is copied into ORBIT and FORGE with ``contracts/claims/`` and ``nova/domain/orion_claims.py``
(docs/CONTRACTS.md). In a copy, set ``SERVICES`` to the service of that repository and adjust the three paths below;
nothing else in this file refers to NOVA. Standard library + pytest only, no IdP and no network.

What fails, in every repository: a fixture or the module edited without refreshing the manifest, a token read with
another audience, a decision that differs from the table written in the fixtures, a contract claim that no fixture
carries any more.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SERVICES = ("orbit",)  # a copy keeps its own service only
ROOT = Path(__file__).resolve().parents[2]
CLAIMS_DIR = ROOT / "contracts" / "claims"
MODULE_PATH = (
    ROOT / "backend" / "app" / "orion_claims.py"
)  # ORBIT copy of NOVA nova/domain/orion_claims.py (same bytes)

_spec = importlib.util.spec_from_file_location("orion_claims_under_test", MODULE_PATH)
assert _spec and _spec.loader
orion_claims = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = orion_claims  # dataclasses resolve their module through sys.modules
_spec.loader.exec_module(orion_claims)

CONTEXT = json.loads((CLAIMS_DIR / "context.json").read_text(encoding="utf-8"))
JWKS = json.loads((CLAIMS_DIR / "jwks.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((CLAIMS_DIR / "manifest.json").read_text(encoding="utf-8"))
CASES = {
    p.stem.removeprefix("case_"): json.loads(p.read_text(encoding="utf-8"))
    for p in sorted(CLAIMS_DIR.glob("case_*.json"))
}
PAIRS = [(name, service) for name in CASES for service in SERVICES]


def evaluate(case: dict, service: str, token_of: str | None = None):
    local = case["services"][service]["local"]
    return orion_claims.evaluate(
        case["tokens"][token_of or service],
        JWKS,
        service=service,
        issuer=CONTEXT["issuer"],
        local_clearance=local["clearance"],
        local_role=local["role"],
        now=CONTEXT["now"],
    )


def payload_of(token: str) -> dict:
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def test_fixtures_and_module_match_the_manifest():
    present = {p.name for p in CLAIMS_DIR.glob("*.json")} - {"manifest.json"}
    assert present == set(MANIFEST["files"]), "files and manifest list differ"
    for name, entry in MANIFEST["files"].items():
        digest = hashlib.sha256((CLAIMS_DIR / name).read_bytes()).hexdigest()
        assert digest == entry["sha256"], (
            f"{name} differs from the manifest hash (edited, or copied from another version)"
        )
    assert hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest() == MANIFEST["module"]["sha256"], (
        "module differs from the manifest hash"
    )
    assert MANIFEST["contract_version"] == orion_claims.CONTRACT_VERSION


@pytest.mark.parametrize(("name", "service"), PAIRS)
def test_decision_matches_the_adr_table(name, service):
    case = CASES[name]
    assert evaluate(case, service).as_dict() == case["services"][service]["expect"]


@pytest.mark.parametrize(("name", "service"), PAIRS)
def test_token_carries_the_claims_written_in_the_fixture(name, service):
    """The readable ``claims`` and the signed token say the same thing (a claim removed / renamed in one fails)."""
    case = CASES[name]
    audience = "some-other-service" if case["defect"] == "audience" else CONTEXT["audiences"][service]
    if case["defect"] == "alg_none":
        assert case["tokens"][service].endswith(".")
    assert payload_of(case["tokens"][service]) == {**case["claims"], "aud": audience}


def test_every_contract_claim_is_carried_by_some_fixture():
    carried = set()
    for case in CASES.values():
        claims = {**case["claims"], "aud": 1}
        carried |= set(claims)
        if "roles" in claims.get("realm_access", {}):
            carried.add("realm_access.roles")
    assert set(MANIFEST["claims"]) <= carried, sorted(set(MANIFEST["claims"]) - carried)


@pytest.mark.parametrize(
    ("name", "service"), [(n, s) for n, s in PAIRS if CASES[n]["services"][s]["expect"]["valid"]]
)
def test_a_token_is_for_one_audience_only(name, service):
    """A valid token of a service is refused by the others (ADR §3: one token per audience)."""
    case = CASES[name]
    for other in SERVICES:
        if other != service and other in case["tokens"]:
            local = case["services"][service]["local"]
            decision = orion_claims.evaluate(
                case["tokens"][service],
                JWKS,
                service=other,
                issuer=CONTEXT["issuer"],
                local_clearance=local["clearance"],
                local_role=local["role"],
                now=CONTEXT["now"],
            )
            assert (decision.valid, decision.error) == (False, "invalid_audience")


@pytest.mark.parametrize(("name", "service"), PAIRS)
def test_invariants_of_the_table(name, service):
    """Rules of ADR §3-§4 that hold for every fixture, whatever its expected values."""
    case = CASES[name]
    entry = case["services"][service]
    decision = evaluate(case, service)
    if not decision.valid:
        assert decision == orion_claims.Decision(
            valid=False, error=decision.error
        )  # a refusal carries no grant at all
        return
    claim = case["claims"].get("orion_clearance")
    assert (
        decision.effective_clearance <= entry["local"]["clearance"]
    )  # the token never raises the local clearance
    if claim is not None:
        assert decision.effective_clearance <= claim
    else:
        assert decision.effective_clearance == entry["local"]["clearance"]  # an absent claim never gives more
    if "orion_workspace_id" not in case["claims"]:
        assert not decision.space_access and decision.workspace_id is None and decision.project_id is None
    assert decision.space_access == (decision.workspace_id is not None)
    if entry["local"]["role"] is None and service == "forge":
        assert decision.role is None  # no local account: the realm role grants nothing


def test_a_token_without_workspace_opens_no_space_resource():
    for name in ("no_workspace", "project_without_workspace"):
        for service in SERVICES:
            claims = orion_claims.validate_token(
                CASES[name]["tokens"][service],
                JWKS,
                issuer=CONTEXT["issuer"],
                audience=CONTEXT["audiences"][service],
                now=CONTEXT["now"],
            )
            for workspace in (
                CASES["standard_user"]["claims"]["orion_workspace_id"],
                "00000000-0000-4000-8000-000000000000",
                None,
            ):
                assert not orion_claims.can_open_space_resource(claims, workspace)
                assert not orion_claims.can_open_project(
                    claims, workspace, CASES["standard_user"]["claims"]["orion_project_id"]
                )


def test_a_token_opens_only_its_own_workspace_and_project():
    case = CASES["standard_user"]
    claims = orion_claims.validate_token(
        case["tokens"]["nova"], JWKS, issuer=CONTEXT["issuer"], audience="nova-web", now=CONTEXT["now"]
    )
    workspace, project = case["claims"]["orion_workspace_id"], case["claims"]["orion_project_id"]
    other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    assert orion_claims.can_open_space_resource(claims, workspace)
    assert not orion_claims.can_open_space_resource(claims, other)
    assert orion_claims.can_open_project(claims, workspace, project)
    assert not orion_claims.can_open_project(
        claims, workspace, other
    )  # a token that names a project opens that one only
    assert not orion_claims.can_open_project(claims, other, project)  # ... and never in another workspace
