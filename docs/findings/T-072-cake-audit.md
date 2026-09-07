# CAKE manual review — gathered for the `bsc-sentry` analyst baseline

**Not the baseline row itself.** `fixtures/manual_baselines.json` requires a
*human* to confirm these findings and record their own *measured* stopwatch time
(the file header forbids computed/estimated numbers). This doc just saves the
legwork so that takes ~2 minutes.

## Target

`0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82` — PancakeSwap Token (CAKE), BSC.

## Findings (gathered 2026-09-07, via BscScan API + BSC RPC)

| Check | Result | Evidence |
|---|---|---|
| Source verified | **yes** | `ContractName = CakeToken`, `CompilerVersion = v0.6.12+commit.27d51765`, `Proxy = 0` (Etherscan v2 multichain, chainid 56) |
| Upgradeable proxy | **no** | `Implementation` empty, no proxy pattern in source |
| Mint function | present, `mint(address,uint256) onlyOwner` | standard BSC BEP20 mintable; `_mint(` present |
| Who can mint | **a contract, not an EOA** | `owner() = 0x73feaa1eE314F8c655E354234017bE2193C9E24E` (PancakeSwap MasterChef), `eth_getCode` at owner = 9156 bytes |
| Ownership | `Ownable` — `renounceOwnership` / `transferOwnership` present | owner is MasterChef; mint is the emission schedule, not a rug lever |
| Blacklist / freeze | **none** | no `blacklist`, no `pause(`, no `setFee` / fee-setter in source |
| Total supply | 5,269,018,771.75 CAKE | `totalSupply()` on-chain |
| Honeypot / transfer tax | not tested here (needs a fork buy/sell) | `bsc-sentry`'s own fork sim covers this — `test_full_report_on_known_good_token` returns verdict OK/WARN |

## Verdict

Consistent with a **known-good reward token**: verified source, no proxy, no
blacklist/pause/fee traps, mint controlled by the MasterChef contract (emission),
not a person. This is the exact "legit reward token mints from a contract" case
that `bsc-sentry` scoring is designed **not** to hard-fail
(`tests/test_sentry.py::test_mint_from_a_contract_owner_is_not_flagged`).

## To turn this into the baseline row

A human: open the contract on BscScan, confirm the above with a stopwatch
running, then add to `fixtures/manual_baselines.json`:

```json
"0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82": {
  "analyst": "<name>",
  "wall_seconds": <your measured seconds>,
  "verdict": "OK",
  "findings": "verified source; not a proxy; mint is onlyOwner and owner is the MasterChef contract (emission, not an EOA); no blacklist/pause/fee functions."
}
```

`bsc-sentry`'s advantage metric is `wall_seconds` (lower is better), so the row
needs at least `wall_seconds`; `verdict` / `findings` make the findings-diff in
`/report` meaningful.
