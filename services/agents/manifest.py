"""The agent manifest schema (spec.md §1).

The marketplace renders ONLY from a validated Manifest plus agent_stats. A
manifest that fails validation makes the agent UNAVAILABLE — it is never rendered
partially (spec.md §1, registry.py).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal["rebalancing", "grid", "yield", "health_factor", "security"]
InputType = Literal["address", "number", "enum", "string", "bool"]
PricingModel = Literal["perf_fee", "flat", "free", "tbd"]


class InputSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: InputType
    required: bool = False
    default: Any = None
    min: float | None = None
    max: float | None = None
    values: list[Any] | None = None  # for type == "enum"

    @model_validator(mode="after")
    def _coherent(self) -> InputSpec:
        if self.type == "enum" and not self.values:
            raise ValueError("enum input needs `values`")
        if self.type != "enum" and self.values:
            raise ValueError("`values` only valid for enum inputs")
        if self.type != "number" and (self.min is not None or self.max is not None):
            raise ValueError("`min`/`max` only valid for number inputs")
        if self.default is not None and self.type == "enum" and self.default not in self.values:
            raise ValueError(f"default {self.default!r} not in {self.values}")
        return self


class AdvantageMetric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    unit: str
    higher_is_better: bool


class Pricing(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: PricingModel
    bps: int | None = None

    @model_validator(mode="after")
    def _bps_iff_perf_fee(self) -> Pricing:
        if self.model == "perf_fee" and self.bps is None:
            raise ValueError("perf_fee pricing needs `bps`")
        if self.model != "perf_fee" and self.bps is not None:
            raise ValueError("`bps` only valid with perf_fee pricing")
        return self

    @property
    def is_set(self) -> bool:
        return self.model != "tbd"


class KillSwitch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_loss_pct: float = Field(gt=0, le=100)


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    category: Category
    one_liner: str
    tiers: list[Literal[0, 1, 2]] = Field(min_length=1)
    inputs: dict[str, InputSpec] = Field(default_factory=dict)
    data_deps: list[str] = Field(default_factory=list)
    baseline: str
    advantage_metric: AdvantageMetric
    pricing: Pricing
    kill_switch: KillSwitch | None = None
    sentry_gate: bool = False

    @model_validator(mode="after")
    def _tier_rules(self) -> Manifest:
        if sorted(set(self.tiers)) != sorted(self.tiers):
            raise ValueError("duplicate tiers")
        if 2 in self.tiers and self.kill_switch is None:
            raise ValueError("a Tier 2 agent must declare a kill_switch (spec.md §S4)")
        return self

    # --- hire-time input validation (spec.md §8: 422 with per-field errors) ---

    def validate_inputs(self, raw: dict[str, Any]) -> dict[str, str]:
        """Return {field: error} for anything wrong with a hire's inputs.
        Empty dict == valid."""
        errs: dict[str, str] = {}
        for name, spec in self.inputs.items():
            if name not in raw or raw[name] is None:
                if spec.required and spec.default is None:
                    errs[name] = "required"
                continue
            v = raw[name]
            if spec.type == "number":
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    errs[name] = "must be a number"
                    continue
                if spec.min is not None and fv < spec.min:
                    errs[name] = f"must be >= {spec.min}"
                elif spec.max is not None and fv > spec.max:
                    errs[name] = f"must be <= {spec.max}"
            elif spec.type == "enum":
                if v not in spec.values:
                    errs[name] = f"must be one of {spec.values}"
            elif spec.type == "address":
                s = str(v)
                if not (s.startswith("0x") and len(s) == 42):
                    errs[name] = "must be a 0x-prefixed 20-byte address"
            elif spec.type == "bool" and not isinstance(v, bool):
                errs[name] = "must be true or false"
        unknown = set(raw) - set(self.inputs)
        for u in unknown:
            errs[u] = "unknown input"
        return errs

    def apply_defaults(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = dict(raw)
        for name, spec in self.inputs.items():
            if (name not in out or out[name] is None) and spec.default is not None:
                out[name] = spec.default
        return out
