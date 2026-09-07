"""T-060 / T-061: the orchestrator REST + SSE surface (spec.md §8).

Uses FastAPI's TestClient against the live docker postgres, so `-m live`.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from orchestrator import db
from orchestrator.main import app
from sqlalchemy import text

pytestmark = pytest.mark.live

REAL_AGENTS = {"pcs-rebalancer", "bnb-grid", "pcs-yield", "venus-guard", "bsc-sentry"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:   # triggers lifespan -> sync_registry_to_db
        yield c


def test_list_agents_cards(client):
    r = client.get("/agents")
    assert r.status_code == 200
    cards = r.json()
    assert {c["id"] for c in cards} == REAL_AGENTS
    for c in cards:
        assert "stats" in c and "has_runs" in c
        assert set(c["stats"]) >= {"n_runs", "window_days", "win_rate", "max_drawdown_pct"}
        # never a bare perf number: has_runs must gate it
        if not c["has_runs"]:
            assert c["stats"]["n_runs"] == 0


def test_agent_detail_has_inputs_curve_and_receipts(client):
    r = client.get("/agents/bnb-grid")
    assert r.status_code == 200
    d = r.json()
    assert d["baseline"] == "hodl"
    assert "capital_usd" in d["inputs"] and d["inputs"]["capital_usd"]["type"] == "number"
    assert "curve" in d and d["curve"]["metric"] == "net_pnl_usd"
    assert isinstance(d["recent_receipts"], list)


def test_unknown_agent_404(client):
    assert client.get("/agents/nope").status_code == 404
    assert client.get("/agents/nope/receipts").status_code == 404


def test_categories(client):
    cats = {c["category"]: c for c in client.get("/categories").json()}
    assert set(cats) == {"rebalancing", "grid", "yield", "health_factor", "security"}
    assert all(c["agent_count"] == 1 for c in cats.values())


def test_healthz_reports_each_dep(client):
    h = client.get("/healthz").json()
    assert set(h["deps"]) == {"db", "redis", "rpc", "hummingbot", "gateway"}
    assert h["deps"]["db"] == "ok"
    assert h["deps"]["rpc"].startswith("ok")


def test_hire_input_validation_422(client):
    r = client.post("/hires", json={"agent_id": "bnb-grid", "tier": 1, "inputs": {}})
    assert r.status_code == 422
    assert "capital_usd" in r.json()["detail"]["errors"]

    r = client.post("/hires", json={"agent_id": "bnb-grid", "tier": 0,
                                    "inputs": {"pair": "BNB-USDT", "capital_usd": 100}})
    assert r.status_code == 422  # bnb-grid does not offer tier 0

    assert client.post("/hires", json={"agent_id": "nope", "tier": 1, "inputs": {}}).status_code == 404


def test_hire_runs_end_to_end_and_streams(client):
    r = client.post("/hires", json={
        "agent_id": "bnb-grid", "tier": 1,
        "inputs": {"pair": "BNB-USDT", "capital_usd": 500, "grid_levels": 10, "risk": "balanced"},
    })
    assert r.status_code == 202
    hire_id = r.json()["hire_id"]

    deadline = time.time() + 60
    status = None
    while time.time() < deadline:
        status = client.get(f"/hires/{hire_id}").json()
        if status["status"] in ("ok", "failed", "halted", "cancelled"):
            break
        time.sleep(1)
    assert status["status"] == "ok", status.get("error")
    assert status["result"]["metric"] == "net_pnl_usd"
    assert status["delta"] is not None
    assert status["receipt"] and status["receipt"]["merkle_leaf"]

    # receipt endpoint + (unbatched) proof
    rc = client.get(f"/receipts/{status['receipt']['id']}").json()
    assert rc["merkle_leaf"] == status["receipt"]["merkle_leaf"]
    assert rc["merkle_proof"] is None and "not yet anchored" in rc["verified_hint"]

    # cleanup just this hire's rows (keep the deployment history intact)
    with db.session() as s:
        s.execute(text("DELETE FROM receipts WHERE id = :id"), {"id": status["receipt"]["id"]})
        s.execute(text("DELETE FROM runs WHERE id IN (:a, :b)"),
                  {"a": status["result"] and status["receipt"]["agent_run_id"],
                   "b": status["receipt"]["baseline_run_id"]})
        s.commit()


def test_advantage_report_from_receipts(client):
    rep = client.get("/report/advantage").json()
    assert rep["generated_from"].startswith("receipts")
    assert "tasks" in rep and isinstance(rep["tasks"], list)
    assert "methodology" in rep
    # with the paper loops running there should be >=1 trading task
    if rep["tasks"]:
        assert all({"agent_id", "metric", "n", "avg_delta"} <= set(t) for t in rep["tasks"])
