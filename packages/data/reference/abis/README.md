# reference/abis/

Canonical ABIs, one JSON file per contract type. Import from here — never inline
an ABI fragment in agent code (R7).

Present:
- `erc20.json` — standard ERC-20 (hand-written, canonical)

Added per consuming task, each fetched from the **verified source on BscScan**
(`https://bscscan.com/address/<addr>#code`) or the official contracts repo, with
the fetch URL noted in that task's journal entry:

| file (planned)            | for                        | added by |
|---------------------------|----------------------------|----------|
| `pancakeV3Pool.json`      | slot0, ticks, liquidity    | T-010    |
| `pancakeV3Factory.json`   | getPool                    | T-010    |
| `nonfungiblePositionManager.json` | positions, mint/burn | T-042/T-043 |
| `quoterV2.json`           | quoteExactInputSingle      | T-030/T-033 |
| `smartRouter.json` / `pancakeV2Router.json` | swaps in the fork sim | T-030 |
| `venusComptroller.json`   | getAccountLiquidity, markets| T-010/T-044 |
| `vToken.json`             | borrowBalance, exchangeRate | T-044   |
| `multicall3.json`         | aggregate3                 | T-010    |

Do not add an ABI before the task that needs it (keeps each one paired with a
real consumer and a real verification).
