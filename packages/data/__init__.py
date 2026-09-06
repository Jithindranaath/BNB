"""proofstand shared data layer.

Ingestion + cache for Binance, PancakeSwap v3 subgraph, BSC RPC, Venus, DefiLlama.
See architecture.md §5 and plan.md Phase 1 (T-010..T-012).

Rule R3: real data or no data. No synthetic prices, ever.
"""

__all__ = ["__version__"]
__version__ = "0.0.0"
