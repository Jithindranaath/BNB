"""Typed source clients (Pydantic returns, retry + backoff). T-010.

One module per external source (architecture.md §5):
  binance.py   OHLCV klines            no auth          -> get_klines()
  subgraph.py  PancakeSwap v3 subgraph GRAPH_API_KEY    -> get_pool(), get_pool_day_datas()  [pending query key]
  rpc.py       BSC RPC via Multicall3  BSC_RPC_URL      -> multicall(), erc20_metadata(), pancake_v3_pool_state()
  venus.py     Venus on-chain reads    on-chain only    -> get_all_markets(), get_account_liquidity(), get_vtoken_snapshot()
  llama.py     DefiLlama TVL + APR     no auth          -> get_pools(), get_pool_chart()
  bscscan.py   verified source / age   BSCSCAN_API_KEY  -> get_contract_source(), is_verified()  [creation NOT on free tier]

Every batch chain read goes through Multicall3 — never loop single eth_calls.
Live tests: tests/test_sources_live.py  (`pytest -m live`).
"""
