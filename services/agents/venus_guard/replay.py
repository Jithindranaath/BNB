"""Replay an account against a real price path (spec.md §7.4) — the receipt that
proves the guard's value.

`no_action`: do nothing; if the health factor crosses 1, a liquidator repays
`close_factor x borrow` and seizes collateral worth `repay x incentive`, so the
user eats `repay x (incentive - 1)`.

`guarded`: when HF < trigger_hf, repay the smallest amount from the pre-approved
buffer that restores HF >= recovery_hf. `usd_saved` = the penalty avoided minus
the gas spent repaying.

Model: all non-stable collateral moves with the dominant asset's price ratio
`k_t = price_t / price_0` (correlated in a crash); stable collateral is fixed.
Pure functions over the ratio path.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    borrow_usd: float
    volatile_collateral_adj_usd: float   # sum(supply_usd * cf) for non-stable collateral, at k=1
    stable_collateral_adj_usd: float     # sum(supply_usd * cf) for stable collateral
    close_factor: float = 0.5
    liquidation_incentive: float = 1.10  # Venus Core Pool (reference/venus_params.json)

    def adj_at(self, k: float, borrow_usd: float | None = None) -> float:
        return self.stable_collateral_adj_usd + self.volatile_collateral_adj_usd * k

    def hf_at(self, k: float, borrow_usd: float | None = None) -> float:
        b = self.borrow_usd if borrow_usd is None else borrow_usd
        return self.adj_at(k) / b if b > 0 else float("inf")


@dataclass
class NoActionResult:
    min_hf: float
    liquidated: bool
    liq_step: int | None
    liq_price_ratio: float | None
    liquidation_loss_usd: float          # the penalty the user pays (>= 0)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def replay_no_action(pos: Position, ratio_path: list[float]) -> NoActionResult:
    min_hf = float("inf")
    for step, k in enumerate(ratio_path):
        hf = pos.hf_at(k)
        min_hf = min(min_hf, hf)
        if hf < 1.0:
            repay = pos.close_factor * pos.borrow_usd
            loss = repay * (pos.liquidation_incentive - 1.0)
            return NoActionResult(min_hf, True, step, k, loss)
    return NoActionResult(min_hf, False, None, None, 0.0)


@dataclass
class GuardedResult:
    min_hf: float
    final_hf: float
    liquidated: bool
    repaid_usd: float
    n_repays: int
    gas_usd: float
    penalty_avoided_usd: float
    usd_saved: float
    actions: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def replay_guarded(
    pos: Position,
    ratio_path: list[float],
    *,
    trigger_hf: float,
    recovery_hf: float,
    buffer_usd: float,
    gas_usd_per_repay: float,
) -> GuardedResult:
    borrow = pos.borrow_usd
    remaining_buffer = buffer_usd
    repaid = 0.0
    gas = 0.0
    n = 0
    min_hf = float("inf")
    actions: list[dict] = []

    for step, k in enumerate(ratio_path):
        hf = pos.hf_at(k, borrow)
        min_hf = min(min_hf, hf)
        if hf < trigger_hf and borrow > 0 and remaining_buffer > 0:
            # smallest repay x so that adj(k) / (borrow - x) >= recovery_hf
            target = pos.adj_at(k) / recovery_hf
            need = max(0.0, borrow - target)
            x = min(need, remaining_buffer, borrow)
            if x <= 0:
                continue
            borrow -= x
            repaid += x
            remaining_buffer -= x
            gas += gas_usd_per_repay
            n += 1
            actions.append({"step": step, "hf_before": round(hf, 4), "repaid_usd": round(x, 2),
                            "hf_after": round(pos.hf_at(k, borrow), 4)})

    liquidated = min_hf < 1.0 and pos.hf_at(min(ratio_path), borrow) < 1.0
    no_act = replay_no_action(pos, ratio_path)
    penalty_avoided = no_act.liquidation_loss_usd if not liquidated else 0.0
    usd_saved = penalty_avoided - gas
    return GuardedResult(
        min_hf=min_hf, final_hf=pos.hf_at(ratio_path[-1], borrow),
        liquidated=liquidated, repaid_usd=repaid, n_repays=n, gas_usd=gas,
        penalty_avoided_usd=penalty_avoided, usd_saved=usd_saved, actions=actions,
    )
