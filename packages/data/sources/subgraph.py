"""PancakeSwap v3 subgraph — pools, poolDayDatas, ticks, positions.
Needs GRAPH_API_KEY. Batch queries, 60s redis TTL. Impl: T-010.
Subgraph id + gateway URL come ONLY from packages/data/reference/subgraphs.json (R1).
"""

from __future__ import annotations

RAISE = NotImplementedError("subgraph source client lands in T-010 (probe first: T-003)")
