"""The five agents, one interface (architecture.md §8).

pcs_rebalancer · bnb_grid · pcs_yield · venus_guard · bsc_sentry

Every agent implements services.agents.base.Agent. No agent makes network calls
outside observe(). decide() is a pure function. Tier 0/1 never construct a signer.
"""
