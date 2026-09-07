"""agent_id -> Agent instance. The API and the hire manager build agents here."""

from __future__ import annotations

from agents.base import Agent

# Agents with a working implementation (a valid manifest alone is not enough).
IMPLEMENTED: dict[str, str | None] = {
    "bsc-sentry": None,
    "bnb-grid": None,
    "pcs-rebalancer": None,
    "venus-guard": None,
    "pcs-yield": None,  # T-033: DefiLlama + on-chain path; Envio v3 feed is an upgrade
}


def is_implemented(agent_id: str) -> bool:
    return IMPLEMENTED.get(agent_id, "unknown agent") is None


def unavailable_reason(agent_id: str) -> str | None:
    r = IMPLEMENTED.get(agent_id, f"no implementation registered for {agent_id!r}")
    return None if r is None else r


def build_agent(agent_id: str, **kwargs) -> Agent:
    if agent_id == "bsc-sentry":
        from agents.bsc_sentry.agent import BscSentryAgent

        return BscSentryAgent()
    if agent_id == "bnb-grid":
        from agents.bnb_grid.agent import BnbGridAgent

        return BnbGridAgent(**kwargs)
    if agent_id == "pcs-rebalancer":
        from agents.pcs_rebalancer.agent import PcsRebalancerAgent

        return PcsRebalancerAgent(**kwargs)
    if agent_id == "venus-guard":
        from agents.venus_guard.agent import VenusGuardAgent

        return VenusGuardAgent(**kwargs)
    if agent_id == "pcs-yield":
        from agents.pcs_yield.agent import PcsYieldAgent

        return PcsYieldAgent(**kwargs)
    if agent_id == "_echo":
        from agents._echo.agent import EchoAgent

        return EchoAgent()
    raise KeyError(f"no agent factory for {agent_id!r}")
