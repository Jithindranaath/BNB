"""Counterfactual runners (architecture.md §9). Implemented in T-023.

  hodl             hold the initial basket, no action          -> bnb-grid
  static_range     one full-range LP position, never touched   -> pcs-rebalancer
  top_headline_apr highest advertised APR, no risk adjustment  -> pcs-yield
  no_action        replay price history, compute liq if HF<1   -> venus-guard
  manual_analyst   human stopwatch, read from fixtures/        -> bsc-sentry

Each runs against the SAME Observation the agent saw and returns a comparable
metric in the agent's declared unit.
"""
