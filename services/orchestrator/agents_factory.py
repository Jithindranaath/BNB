"""agent_id -> Agent instance. The API and the hire manager build agents here."""

from __future__ import annotations

from agents.base import Agent


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
        raise NotImplementedError("pcs-yield (T-033) is held pending a Graph query key")
    if agent_id == "_echo":
        from agents._echo.agent import EchoAgent

        return EchoAgent()
    raise KeyError(f"no agent factory for {agent_id!r}")
