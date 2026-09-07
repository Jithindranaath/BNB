"""T-060 / T-061: the orchestrator REST + SSE surface (spec.md §8).

Uses FastAPI's TestClient against the live docker postgres, so `-m live`.
"""

from __future__ import annotations

import json
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


def test_pcs_yield_shows_but_is_marked_unavailable(client):
    """T-072: the yield category tile + card still render (main-track diversity),
    but pcs-yield has no implementation yet — the card says so and a hire 409s
    instead of failing deep in a worker thread."""
    cards = {c["id"]: c for c in client.get("/agents").json()}
    y = cards["pcs-yield"]
    assert y["available"] is False and y["unavailable_reason"]
    assert cards["bsc-sentry"]["available"] is True

    d = client.get("/agents/pcs-yield").json()
    assert d["available"] is False

    r = client.post("/hires", json={"agent_id": "pcs-yield", "tier": 0,
                                    "inputs": {"capital_usd": 500}})
    assert r.status_code == 409
    assert "T-033" in r.json()["detail"]


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


def test_hire_stream_delivers_phase_events(client):
    """T-061: consume /hires/{id}/stream as SSE and confirm phase events land,
    ending with a terminal status — not just poll /hires/{id}."""
    r = client.post("/hires", json={
        "agent_id": "bnb-grid", "tier": 1,
        "inputs": {"pair": "BNB-USDT", "capital_usd": 500, "grid_levels": 10, "risk": "balanced"},
    })
    assert r.status_code == 202
    hire_id = r.json()["hire_id"]

    phases: list[str] = []
    last_status = None
    with client.stream("GET", f"/hires/{hire_id}/stream") as s:
        assert s.status_code == 200
        assert "text/event-stream" in s.headers["content-type"]
        for line in s.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            evt = json.loads(line[5:].strip())
            if evt.get("phase"):
                phases.append(evt["phase"])
            last_status = evt.get("status", last_status)
            if evt.get("phase") == "closed" or last_status in ("ok", "failed", "halted"):
                break

    assert "connected" not in phases  # 'connected' is a message, not a phase
    assert {"observe", "decide", "report"} & set(phases), phases
    assert phases[-1] in ("done", "closed")
    assert last_status in ("ok", "failed", "halted")

    # tidy up this hire's rows, keep deployment history
    status = client.get(f"/hires/{hire_id}").json()
    if status.get("receipt"):
        with db.session() as s:
            s.execute(text("DELETE FROM receipts WHERE id = :id"), {"id": status["receipt"]["id"]})
            s.execute(text("DELETE FROM runs WHERE id IN (:a, :b)"),
                      {"a": status["receipt"]["agent_run_id"],
                       "b": status["receipt"]["baseline_run_id"]})
            s.commit()


def test_advantage_report_from_receipts(client):
    rep = client.get("/report/advantage").json()
    assert rep["generated_from"].startswith("receipts")
    assert isinstance(rep["tasks"], list)
    assert "methodology" in rep and "generated_at" in rep
    # every spec §10 task is accounted for, run or not
    planned_ids = {p["agent_id"] for p in rep["planned"]}
    assert planned_ids == {"bnb-grid", "bsc-sentry", "pcs-rebalancer", "pcs-yield"}
    for p in rep["planned"]:
        assert p["status"] in ("has receipts", "not yet run")
        if p["status"] == "not yet run":
            assert p["reason"]  # never a silent gap

    for t in rep["tasks"]:
        assert {"agent_id", "metric", "n", "kind", "time", "cost", "output_quality",
                "outputs", "evaluation_window_days", "receipts_span_days"} <= set(t)
        assert t["kind"] in ("BACKTEST", "LIVE")
        assert t["both_ways"] is True
        assert len(t["outputs"]) == min(t["n"], 12)
        for o in t["outputs"]:
            assert o["url"] == f"/receipt/{o['receipt_id']}"
        # a backtest must state its replay method; a live run must not carry one
        assert (t["replay_method"] is not None) == (t["kind"] == "BACKTEST"
                                                    and t["category"] in
                                                    ("grid", "rebalancing", "health_factor"))
        # simulated runs report $0, never a made-up gas number
        if not t["cost"]["on_chain"]:
            assert t["cost"]["agent_gas_bnb"] == 0 and t["cost"]["note"]

    # backtests are listed apart from live numbers, never blended
    assert set(rep["backtested_tasks"]) == {
        t["agent_id"] for t in rep["tasks"] if t["kind"] == "BACKTEST"
    }


def test_advantage_report_pdf(client):
    r = client.get("/report/advantage.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-" and len(r.content) > 1000
