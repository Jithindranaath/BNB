# reference/abis/

Canonical ABIs, one JSON file per contract type. Import from here — never inline
an ABI fragment in agent code (R7).

Present:
- `erc20.json` — standard ERC-20 (hand-written, canonical)

**Note (T-010):** `packages/data/sources/rpc.py` and `venus.py` do **not** use full
ABI JSON files. Each read is an explicit
`Call(target, "name(argtypes)", args, ("out","types"))` — 4-byte selector +
`eth_abi` encode/decode, the same shape as `scripts/probe/bsc_rpc_multicall.ts`.
This keeps every chain read visible at the call site with no hidden ABI, and
side-steps needing verified ABIs for contracts BscScan won't serve on the free
tier. One quirk pinned down this way: PancakeSwap v3 `slot0()` returns
`feeProtocol` as **uint32** (not `uint8` like Uniswap v3).

Full ABI files still get added here when a task genuinely needs `w3.eth.contract`
objects (event decoding, tx building) rather than plain reads — fetched from the
**verified source on BscScan** or the official contracts repo, URL noted in the
task's journal entry:

| file (planned)            | for                          | added by |
|---------------------------|------------------------------|----------|
| `nonfungiblePositionManager.json` | positions, mint/burn, tx building | T-042/T-043 |
| `pancakeV3Pool.json`      | Mint/Burn/Swap event decoding | T-030/T-042 |
| `receiptAnchor.json`      | BatchAnchored event           | T-062    |

Do not add an ABI before the task that needs it.
