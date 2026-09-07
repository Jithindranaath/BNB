# Acceptance pass — spec.md §11 (T-071)

Walked 2026-09-07. Each item verified by running the command / test named, not
from memory. A partial is recorded as a partial — the exact blocker is stated.

| # | Criterion | Result |
|---|---|---|
| 1 | Cold `data pull` → real 30d OHLCV frame < 2 min | **PASS** |
| 2 | `verify_reference.ts` passes; every address `verified: true` + source | **PASS** |
| 3 | A test proves `decide()` is pure | **PASS** |
| 4 | A test proves Tier 0/1 cannot sign | **PASS** |
| 5 | All five agents complete a run + receipt with a baseline | **PARTIAL — 3/5** |
| 6 | Stranger reaches a real `bsc-sentry` result from `/`, no wallet, < 2 min | **PARTIAL** |
| 7 | Every performance number in the UI shows `n` and window | **PASS** |
| 8 | ≥1 receipt batch anchored on BSC, merkle proof verifies client-side | **PARTIAL — proven on a local chain, not mainnet** |
| 9 | `/report` renders ≥3 both-ways tasks, real outputs, ≥1 trading/security | **PASS** |
| 10 | `/healthz` reports every dependency, and the public URL is up | **PARTIAL — healthz PASS, public URL not deployed** |

**5 PASS, 4 PARTIAL, 0 fake passes.** The four partials trace to three external
blockers, all already tracked:

- **No public deploy yet** (T-070) — the deploy artifacts are built and were run
  locally, but the hosted site needs the user's GitHub / Render / Vercel
  accounts. Blocks the "public URL" half of #6 and #10.
- **Funded keys** — `ANCHOR_PRIVATE_KEY` + BNB for gas (#8), `SESSION_KEY_PRIVATE_KEY`
  for Tier-2 live (T-041 / T-043).
- **`fixtures/manual_baselines.json` has no real human audit** (only the sample
  row) and **The Graph query key** is not live (T-033) — together these keep
  `bsc-sentry` and `pcs-yield` from forming a both-ways receipt (#5), and make a
  `bsc-sentry` *marketplace hire* fail at the baseline step (#6).

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

## 5. Five agents → run + receipt with a baseline — PARTIAL (3/5)

Real both-ways receipts in the dev DB right now:

| agent | category | n | baseline | status |
|---|---|---|---|---|
| `bnb-grid` | grid | 5 | hodl | OK |
| `pcs-rebalancer` | rebalancing | 5 | static_range | OK |
| `venus-guard` | health_factor | 1 | no_action | OK |
| `bsc-sentry` | security | 0 | manual_analyst | **blocked** |
| `pcs-yield` | yield | 0 | top_headline_apr | **blocked** |

- `bsc-sentry` **runs** and produces a real verdict + per-check evidence on
  mainnet (`tests/test_sentry.py::test_full_report_on_known_good_token`, live,
  2 pass), but its baseline is a human analyst timed with a stopwatch and
  `fixtures/manual_baselines.json` holds only the sample row — so no both-ways
  receipt. R2/R3 forbid inventing the human number. Fix: a teammate records one
  real audit (address, wall seconds, findings) into that file.
- `pcs-yield` is held for a working Graph query key (T-033); it needs the PCS v3
  subgraph to route.

The receipt schema requires a baseline (`baseline_run_id NOT NULL`), so "runs but
no baseline" cannot itself be persisted as a receipt — by design.

## 6. Stranger → real `bsc-sentry` result from `/`, no wallet — PARTIAL

What works, verified locally:

- Landing (`/`) shows the four category tiles and the CTA
  **"Try an agent — no wallet needed"** deep-linking to
  `/agent/bsc-sentry?target=0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82` (CAKE).
- The sentry check suite runs on real BSC and returns a verdict (`OK` / `WARN` /
  `CRITICAL`) with evidence on every line — `tests/test_sentry.py` live, 2 pass;
  the honeypot case correctly returns `CRITICAL` with the sell-revert string as
  evidence.

What is not verifiable end to end:

- **Public URL is not live** (T-070) — cannot do the "from a cold phone" run.
- A `bsc-sentry` **hire through the marketplace** currently fails at the baseline
  step for any token with no recorded manual audit (see #5), so the SSE run view
  would show an error rather than the verdict. The verdict path itself is not
  blocked; the both-ways wrapper is.

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

Full flow proven against a local Anvil chain:

```
$ python scripts/anchor_receipts.py
deployed ReceiptAnchor -> 0x… (local anvil)
anchored: tx … block 6
event root == batch root: OK   proof verifies: True
```

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

## 10. `/healthz` reports every dependency + public URL up — PARTIAL

`GET /healthz` reports `db`, `redis`, `rpc`, `hummingbot`, `gateway` individually
and returns `status: "ok"` when `db` and `rpc` are ok (Redis down does not
degrade it — Redis is optional). Verified against the Dockerised orchestrator run
locally:

```
{"status":"ok","deps":{"db":"ok","redis":"down","rpc":"ok (block 120532197)",
 "hummingbot":"not_configured (T-041)","gateway":"not_configured (T-004 profile)"}}
```

**Public URL is not up** — deploy artifacts (Dockerfile, `render.yaml`,
`vercel.json`, `docs/deploy.md`) are done and the image was proven locally, but
the hosted deploy is the user's step (T-070).

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
