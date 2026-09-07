"""Response models for the orchestrator API (spec.md §8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agents.manifest import AdvantageMetric, InputSpec, Pricing
from pydantic import BaseModel


class AgentStatsOut(BaseModel):
    n_runs: int = 0
    window_days: float | None = None
    median_wall_seconds: float | None = None
    win_rate: float | None = None
    median_delta: float | None = None
    worst_delta: float | None = None
    max_drawdown_pct: float | None = None
    updated_at: datetime | None = None

    @property
    def has_runs(self) -> bool:
        return self.n_runs > 0


class AgentCard(BaseModel):
    id: str
    name: str
    category: str
    one_liner: str
    tiers: list[int]
    pricing: Pricing
    advantage_metric: AdvantageMetric
    sentry_gate: bool = False
    available: bool = True
    unavailable_reason: str | None = None
    stats: AgentStatsOut
    has_runs: bool


class Curve(BaseModel):
    """Aligned agent vs baseline value series over the receipt feed."""

    metric: str
    unit: str
    window_days: float | None
    points: list[dict[str, Any]]  # [{created_at, agent_value, baseline_value, delta}]


class AgentDetail(AgentCard):
    inputs: dict[str, InputSpec]
    data_deps: list[str]
    baseline: str
    kill_switch: dict[str, Any] | None = None
    recent_receipts: list[ReceiptOut]
    curve: Curve


class ReceiptOut(BaseModel):
    id: str
    agent_id: str
    agent_run_id: str
    baseline_run_id: str
    metric: str
    unit: str
    agent_value: float
    baseline_value: float
    delta: float
    favorable: bool
    merkle_leaf: str
    batch_id: str | None = None
    anchored_tx: str | None = None
    created_at: datetime


class ReceiptDetail(ReceiptOut):
    merkle_proof: list[str] | None = None
    anchor_root: str | None = None
    verified_hint: str


class CategoryOut(BaseModel):
    category: str
    agent_count: int
    live_runs: int


class HireCreated(BaseModel):
    hire_id: str
    run_id: str | None = None
    status: str


class HireStatus(BaseModel):
    hire_id: str
    agent_id: str
    tier: int
    status: str                       # queued | running | ok | failed | halted | cancelled
    phase: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    receipt: ReceiptOut | None = None
    delta: float | None = None
    favorable: bool | None = None


class HealthReport(BaseModel):
    status: str
    deps: dict[str, str]


AgentDetail.model_rebuild()
