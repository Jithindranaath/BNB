"""Typed source clients (Pydantic returns, retry+backoff). Implemented in T-010.

One module per external source (architecture.md §5):
  binance.py   OHLCV klines            (no auth)
  subgraph.py  PancakeSwap v3 subgraph (GRAPH_API_KEY)
  rpc.py       BSC RPC, multicall3     (BSC_RPC_URL; never loop single calls)
  venus.py     Venus lending reads     (on-chain reads only)
  llama.py     DefiLlama TVL + APR     (no auth)
  bscscan.py   verified source, age    (BSCSCAN_API_KEY; token-bucket 4 req/s)

Rule R5: probe an API under scripts/probe/ and print the real response before
writing a typed client for it.
"""
