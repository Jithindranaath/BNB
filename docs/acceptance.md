# Acceptance pass — spec.md §11 (T-071)

Walked 2026-09-07; #5 and #33-related items refreshed 2026-09-08; #5, #6, #10
refreshed again 2026-09-09 after T-070 (hosted deploy) and T-072 (CAKE
manual-analyst row) landed. Each item verified by running the command / test
named, not from memory. A partial is recorded as a partial — the exact blocker
is stated.

| # | Criterion | Result |
|---|---|---|
| 1 | Cold `data pull` → real 30d OHLCV frame < 2 min | **PASS** |
| 2 | `verify_reference.ts` passes; every address `verified: true` + source | **PASS** |
| 3 | A test proves `decide()` is pure | **PASS** |
| 4 | A test proves Tier 0/1 cannot sign | **PASS** |
| 5 | All five agents complete a run + receipt with a baseline | **PASS — 5/5** |
| 6 | Stranger reaches a real `bsc-sentry` result from `/`, no wallet, < 2 min | **PARTIAL — API verified live, browser/phone walkthrough pending** |
| 7 | Every performance number in the UI shows `n` and window | **PASS** |
| 8 | ≥1 receipt batch anchored on BSC, merkle proof verifies client-side | **PARTIAL — proven on a local chain, not mainnet** |
| 9 | `/report` renders ≥3 both-ways tasks, real outputs, ≥1 trading/security | **PASS** |
| 10 | `/healthz` reports every dependency, and the public URL is up | **PASS** |

**7 PASS, 2 PARTIAL, 0 fake passes.** Refreshed 2026-09-09 after T-070 (hosted
deploy) went live and the T-072 CAKE manual-analyst row landed. The two
remaining partials trace to funded keys only:

- **Funded keys** — `ANCHOR_PRIVATE_KEY` + BNB for gas (#8), `SESSION_KEY_PRIVATE_KEY`
  for Tier-2 live (T-041 / T-043).
- **#6's browser/phone leg is unverified**, not blocked — the API-level hire
  now succeeds against the live site (see §6 below); what's left is the actual
  cold-browser and cold-phone walkthrough, tracked as step C in
  `docs/human-steps.md`.

---

## 1. Cold `data pull` → real 30d OHLCV < 2 min — PASS

```
$ rm -f packages/data/.cache/klines/BNBUSDT_1h.parquet
$ python -m data pull --pair BNB-USDT --days 30 --interval 1h
[data pull] BNB-USDT 1h 30d: 720 candles  2026-08-08T18:00 -> 2026-09-07T17:00  in 0.53s
real 0m2.020s
```

720 real Binance candles (30d × 1h), 0.53 s of network + parse. `docker compose
up` (postgres / redis / anvil) is a prerequisite and was already healthy.

## 2. `verify_reference.ts` — PASS

```
$ cd scripts && npx tsx verify_reference.ts
  ok  addresses.*  (10/10 contracts)
  ok  tokens.*     (5/5 tokens: symbol + decimals confirmed on-chain)
  --  subgraphs.pancakeswapV3Bsc / venusBsc: PENDING (needs a Graph query key)
OK — 15 address/token entries verified on-chain. 2 subgraph(s) pending.
```

All 10 contract addresses and 5 token addresses carry `verified: true` with a
source URL and were re-checked on BSC mainnet by the script. The two `subgraphs`
entries are subgraph IDs, not addresses; they stay `verified: false` until a
Graph query key exists (T-033) and are read through an R1-guarded accessor that
raises rather than returning an unverified value.

## 3. `decide()` is pure — PASS

`services/orchestrator/harness.py::assert_pure` calls `decide(obs)` twice on the
same frozen `Observation` and requires an identical `Decision`; every hire runs
it. Direct tests:

```
$ pytest -q tests/test_tier.py tests/test_harness.py -k "pure or sign or signer or tier"
7 passed
```

`tests/test_venus_guard.py::test_venus_guard_hire_vs_no_action` also asserts
`agent.decide(obs) == agent.decide(obs)` on a real on-chain observation.

## 4. Tier 0/1 cannot sign — PASS

`tests/test_tier.py`: `ExecContext.for_tier(0|1, signer=<key>)` drops the signer
(`ctx.signer is None`), `require_signer()` raises `TierViolation`, the dataclass
is frozen, and Tier 2 requires a signer. The harness additionally raises if a
Tier 0/1 agent's `act()` returns signed actions. 7/7 pass (item 3 run above).

## 5. Five agents → run + receipt with a baseline — PASS (5/5)

Real both-ways receipts:

| agent | category | n | baseline | status |
|---|---|---|---|---|
| `bnb-grid` | grid | 5 | hodl | OK |
| `pcs-rebalancer` | rebalancing | 5 | static_range | OK |
| `pcs-yield` | yield | 1 | top_headline_apr | OK (2026-09-08) |
| `venus-guard` | health_factor | 1 | no_action | OK |
| `bsc-sentry` | security | 1 | manual_analyst | **OK (2026-09-09)** |

- `pcs-yield` (T-033) now ships on DefiLlama (PancakeSwap v2 BSC) + Binance vol +
  the on-chain sentry gate. A real hire ranks the v2 pool universe and beats the
  naive `top_headline_apr` pick by ~3.8 pp (`tests/test_pcs_yield.py`, live).
  The v3 fee/day-data upgrade is a self-hosted Envio indexer, `docs/envio-indexer.md`.
- `bsc-sentry` now has a real both-ways receipt against the live API
  (`https://proofstand-orchestrator.onrender.com`): CAKE audited manually with
  a stopwatch (`fixtures/manual_baselines.json`, 54s, T-072) vs the agent's
  4.57s → **delta -49.4s, favorable**, receipt `38d51918-a513-4b6c-8ec9-ffe220f81bb3`.
  Landing this also surfaced and fixed a real bug: `BscSentryAgent.observe()`
  never wrote `inputs` into `Observation.data` (every other agent does), so
  `baseline_manual_analyst` could not resolve *any* target's baseline until
  that was added — the missing JSON row was only half the blocker.
- **Known degradation, not a bug:** the live check's `source_verified` axis
  reads `warn` ("BscScan has no verified source") because `BSCSCAN_API_KEY` is
  unset on Render (optional per `render.yaml`). The human audit *did* confirm
  the source is verified by reading BscScan directly. Set the key before demo
  day if you want the live verdict to reflect that.

The receipt schema requires a baseline (`baseline_run_id NOT NULL`), so "runs but
no baseline" cannot itself be persisted as a receipt — by design.

## 6. Stranger → real `bsc-sentry` result from `/`, no wallet — PARTIAL

What's now verified against the live site:

- `https://proofstand-orchestrator.onrender.com/healthz` → `status: ok`.
- `POST /hires` for `bsc-sentry` + the CAKE address succeeds end to end against
  the live API and returns the real receipt described in §5 above — the
  both-ways wrapper that used to fail at the baseline step now works.
- Landing (`/`) shows the four category tiles and the CTA
  **"Try an agent — no wallet needed"** deep-linking to
  `/agent/bsc-sentry?target=0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82` (CAKE).
- The sentry check suite runs on real BSC and returns a verdict (`OK` / `WARN` /
  `CRITICAL`) with evidence on every line — `tests/test_sentry.py` live, 2 pass;
  the honeypot case correctly returns `CRITICAL` with the sell-revert string as
  evidence.

What's still open — not blocked, just not walked yet:

- The actual **browser click-through** on the deployed Vercel frontend (CTA →
  run view → verdict rendering), and the **cold-phone** pass from
  `docs/deploy.md` §4 / `docs/demo.md`'s rehearsal log. This is step C in
  `docs/human-steps.md` — needs a person, a phone, and a stopwatch, not more
  engineering.

## 7. Every UI performance number shows `n` + window — PASS

- Agent cards — `apps/web/lib/api.ts::fmtAdvantage`: returns `"No runs yet"` when
  `!has_runs`; otherwise the string always contains `n=<n_runs> · <window>d`.
- Agent detail (`app/agent/[id]/page.tsx`) — a "runs" row shows
  `n=<n> · <window>d` or "No runs yet"; the advantage / max-drawdown figure sits
  in the same stats table.
- Compare (`app/category/[slug]/compare.tsx`) — aligned rows "n runs",
  "window (d)", "median advantage" (→ "No runs yet" when null).
- Curve (`components/Curve.tsx`) — chart caption `window: <n>d · n=<n>`.
- Report (`app/report/page.tsx`) — per-task `n` and `evaluation window` fields.

## 8. Receipt batch anchored on BSC + client-side proof — PARTIAL

Full flow proven against a local Anvil chain, and now run against the **live**
DB (2026-09-09) — all 20 receipts on the deployed site batched and anchored:

```
$ python scripts/anchor_receipts.py --min-size 1     # DATABASE_URL = live Render/Neon
batch 19870816-...: 20 receipts, root 0xa86aaf60...
deployed ReceiptAnchor -> 0x5FbDB2315678afecb367f032d93F642f64180aa3 (local anvil; no mainnet key set)
anchored: tx 374d4726... block 2
event root == batch root: OK   proof verifies: True
```

Confirmed via the live API — `GET /receipts/{id}` now returns a populated
`merkle_proof` array and `anchor_root`, so `components/MerkleVerifier.tsx`
renders the green checkmark instead of "verifier idle — batch this receipt
first". **This was previously a silent demo-breaking gap**: 0/20 live receipts
were anchored before this run, which would have failed demo beat #4
(`docs/demo.md`) for every receipt.

**Re-run this before the actual demo.** The paper-loop and rehire jobs keep
producing new receipts after this batch, which start out unbatched again —
`python scripts/anchor_receipts.py` right before going on stage (per
`docs/demo.md`'s pre-demo checklist step 3) picks up everything new.

`scripts/anchor_receipts.py` deploys `ReceiptAnchor.sol`, batches leaves, calls
`anchor(batchId, root, count)`, reads back the `BatchAnchored` event, and
recomputes the Merkle proof with the **same sorted-pair keccak fold the browser
uses** (`components/MerkleVerifier.tsx`, `@noble/hashes`). `tests/test_anchor.py`
(10 pass) covers the proof/verify round-trip for n ∈ {1,2,3,4,5,8,13} incl. the
odd-tail case.

**Not done on BSC mainnet** — needs `ANCHOR_PRIVATE_KEY` + BNB for gas (T-062).

## 9. `/report` ≥3 both-ways, real outputs, ≥1 trading/security — PASS

```
n_tasks_with_data 3 | meets_min_3_bothways True | has_trading_or_security True
  bnb-grid        BACKTEST n=5 win_rate=1.0  5 receipt links
  pcs-rebalancer  BACKTEST n=5 win_rate=1.0  5 receipt links
  venus-guard     BACKTEST n=1 win_rate=1.0  1 receipt link
```

Three both-ways tasks, each with per-task time / cost / output-quality, explicit
`n`, `evaluation_window_days` (from the agent's own result) vs `receipts_span_days`,
and `/receipt/<id>` links. All three are trading / health_factor, so ≥1
trading/security holds twice over. Every one is labelled `BACKTEST` with its
replay method stated; the two spec §10 tasks with no data (`bsc-sentry`,
`pcs-yield`) render in `planned[]` with a reason. `GET /report/advantage.pdf`
returns a valid PDF (`tests/test_api.py::test_advantage_report_pdf`).

## 10. `/healthz` reports every dependency + public URL up — PASS

`GET /healthz` reports `db`, `redis`, `rpc`, `hummingbot`, `gateway` individually
and returns `status: "ok"` when `db` and `rpc` are ok (Redis down does not
degrade it — Redis is optional). T-070 is live; verified against the public URL
2026-09-09:

```
$ curl https://proofstand-orchestrator.onrender.com/healthz
{"status":"ok","deps":{"db":"ok","redis":"down","rpc":"ok (block 120906010)",
 "hummingbot":"not_configured (T-041)","gateway":"not_configured (T-004 profile)"}}
```

The Vercel frontend URL wiring and CORS pin (`docs/human-steps.md` step A3)
should still be double-checked before demo day, but the public-URL-up half of
this criterion is satisfied.

---

## Test suite state (2026-09-07)

```
$ pytest -q -m "not live"   → 70 passed
$ pytest -q -m "live"       → 41 passed, 1 skipped
```

Total **111 passed, 1 skipped**. The skip is
`tests/test_sources_live.py::…subgraph…` (needs `GRAPH_API_KEY`).

### Fixed during this pass

`tests/test_db_migration.py` ran `alembic downgrade base` / `upgrade head`
against the **dev database**, which dropped `runs` + `receipts` on every
`-m live` run — silently destroying the data `/report` and this acceptance pass
depend on. Rewritten to create and drop a throwaway `proofstand_migtest`
database; the dev DB is no longer touched by the suite. Verified: a full
`-m live` run now leaves all receipts intact.
