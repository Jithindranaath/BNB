# scripts/probe/  (rule R5)

One script per external source. Each prints the **raw** response to
`scripts/probe/output/<source>.json` (or `.txt`). Do not write a typed client
in `packages/data/sources/` for a response you have not printed here first.

T-003 creates:

| script                | source            | needs                 |
|-----------------------|-------------------|-----------------------|
| `binance_klines.ts`   | Binance klines    | —                     |
| `pcs_subgraph.ts`     | PCS v3 subgraph   | `GRAPH_API_KEY`       |
| `bsc_rpc_multicall.ts`| BSC RPC multicall | `BSC_RPC_URL`         |
| `venus_reads.ts`      | Venus on-chain    | `BSC_RPC_URL`         |
| `defillama_pools.ts`  | DefiLlama pools   | —                     |
| `bscscan_source.ts`   | BscScan source    | `BSCSCAN_API_KEY`     |

Any source that fails is reported `BLOCKED` with the error — not worked around.
