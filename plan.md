# plan.md

> Read after `spec.md`. This is the work queue.
> Do **one task at a time**. Do not start a task with unmet dependencies.
> Update `Status` when you finish. Commit as `[T-00X] <what changed>`.
> If a task exceeds ~90 minutes of tool calls, stop and report the blocker.

Status values: `TODO` · `WIP` · `DONE` · `BLOCKED(reason)`

---

## Phase 0 — Ground truth (do not skip; everything else depends on it)

### T-001 · Repo scaffold · DONE
Create the layout in `architecture.md` §2. Root `docker-compose.yml` with postgres+timescale, redis, anvil. `.env.example` with every var named (no values). Python 3.11 venv, `pyproject.toml`. Next.js app.
**Accept:** `docker compose up` brings postgres, redis, anvil healthy. `pytest` and `npm run dev` both start clean.
**Deps:** none

### T-002 · Populate and verify reference data · DONE
> addresses.json + tokens.json: 15 entries, all verified on-chain (bytecode +
> identity call) via `verify_reference.ts`, exit 0. subgraphs.json: IDs recorded,
> `verified:false` — live resolution needs GRAPH_API_KEY, done in T-003.
> ABIs: `erc20.json` added; protocol ABIs added per consuming task (abis/README.md).
Fill `packages/data/reference/addresses.json`, `tokens.json`, `subgraphs.json`, `abis/`.
**Rule R1 applies absolutely: do not write any address from memory.** Open the official PancakeSwap developer docs and Venus docs, copy each address, paste the doc URL into the `source` field. Write `scripts/verify_reference.ts`: for each address, assert bytecode exists on BSC, and where possible call a known method (e.g. factory `owner()`, position manager `factory()`) to confirm identity. Only then flip `verified: true`.
**Accept:** `npx tsx scripts/verify_reference.ts` exits 0; zero entries with `verified: false`.
**Deps:** T-001

### T-003 · Probe every external API · DONE
> 6 probes written + run. **OK:** Binance klines, DefiLlama pools+chart, BSC RPC
> multicall3, Venus on-chain reads. **BLOCKED (recorded):** PCS v3 subgraph
> (GRAPH_API_KEY), BscScan (BSCSCAN_API_KEY) — re-run steps in docs/findings/T-003.md.
> Finding: Venus Core Comptroller is an EIP-2535 Diamond — see T-044 note.
Under `scripts/probe/`, one script per source: Binance klines, PCS v3 subgraph (confirm the subgraph ID resolves and return one pool), BSC RPC multicall, Venus reads, DefiLlama pools, BscScan source fetch. Print raw responses to `scripts/probe/output/`.
**Rule R5: do not write a typed client for a response you have not printed.**
**Accept:** six probe outputs on disk, each with a real response. Any failing source is reported as `BLOCKED` with the error, not worked around silently.
**Deps:** T-002

### T-004 · Gateway PancakeSwap capability probe · DONE — **HIGH PRIORITY, DAY 1**
> **Gateway v2.16.0 CAN write to PancakeSwap v3 on BSC** — clmm routes
> open/add/remove/close/collect + swap, `bsc` in supported networks, verified in
> source + a live container. Not quote-only. Stock image needs BSC RPC config
> (T-041/T-043); no on-chain tx run yet (T-043). Primary path = Gateway, fallback
> = viem NonfungiblePositionManager kept until T-043. See docs/findings/T-004.md.
Bring up `hummingbot-api` + `gateway`. Determine whether Gateway can *write* to PancakeSwap on BSC (add/remove liquidity, swap) or only quote prices. The Hummingbot skills list PancakeSwap only as an arbitrage price source, so assume quote-only until proven otherwise.
**Accept:** a written finding in `docs/findings/T-004.md` stating exactly what works, with the commands and responses. If quote-only → `pcs-rebalancer` executes via our own viem position manager (spec §6.3) and you note that here.
**Deps:** T-001

---

## Phase 1 — Data layer (everything blocks on this)

### T-010 · Source clients · DONE
> `binance` `llama` `rpc` `venus` `bscscan` — live tests pass (`pytest -m live`,
> 7 pass / 1 skip). `subgraph.py` written; its live test auto-skips until a real
> Graph **query** key lands (deploy key was supplied — docs/findings/T-003.md).
> rpc.py: all batch reads via Multicall3 `aggregate3`, dual-provider fallback,
> explicit `Call(sig, args, out-types)` (no hidden ABI). Found: PCS v3 `slot0()`
> `feeProtocol` is uint32, not uint8.
`packages/data/sources/`: `binance.py`, `subgraph.py`, `rpc.py`, `venus.py`, `llama.py`, `bscscan.py`. Typed returns (Pydantic). Retry with backoff. BscScan token-bucketed at 4 req/s. RPC uses multicall3 for any batch read — never loop single calls.
**Accept:** unit test per source hitting the live API and asserting a non-empty typed result.
**Deps:** T-003

### T-011 · Cache + CLI · DONE
> `cache.read_klines()` — parquet per `{SYMBOL}_{interval}`, append-tail only
> (truncate→restore test: no dupes, monotonic). Cold 30d/1h **0.94s**, warm
> **0.55s**, cached-only **0.05s**. `cache.hot_json(key,ttl,producer)` — redis
> with graceful bypass; TTLs per §5. `python -m data pull|info` (+ editable
> install now exposes `data`, `agents.*`, `orchestrator`). tests/test_cache.py.
`cache.py`: parquet on disk for klines/poolDayDatas (append tail only, never refetch history), redis for hot state with per-source TTLs from `architecture.md` §5. `cli.py`: `python -m data pull --pair BNB-USDT --days 30`.
**Accept:** cold run pulls 30d of 1h klines in <60s; second run hits cache in <2s; parquet survives container restart.
**Deps:** T-010

### T-012 · Calibration functions · DONE
> `atr` (Wilder), `realized_vol` (annualised log-return stdev), `fee_apr`,
> `il_estimate` (numerical E[IL] of a bounded v3 range under drift-free lognormal
> price; assumptions documented inline), `gas_cost_usd`. Each tested vs an
> independent computation on a frozen REAL fixture (`fixtures/klines_bnbusdt_1h.csv`).
> `scripts/measure_gas.py` measured wrap/approve/swap_v2 on an Anvil BSC fork ->
> `fixtures/gas_units.json` (block 120493611); v3-NPM + venus ops `verified:false`
> -> `gas_cost_usd` raises `GasUnitUnmeasured` for them (filled in T-042/T-044).
Implement `spec.md` §2. `gas_cost_usd` must be derived from gas units **measured on the Anvil fork**, written to `fixtures/gas_units.json` with the measurement block. Document the v3 IL formula and its assumptions inline.
**Accept:** each function tested against a hand-computed value on a fixed kline fixture. No synthetic data anywhere (R3).
**Deps:** T-011

---

## Phase 2 — Harness and receipts (the scoring primitive)

### T-020 · Agent base + manifest loader · WIP
`services/agents/base.py` per `architecture.md` §8. `registry.py` loads and Pydantic-validates every `manifest.yaml`; an invalid manifest makes the agent unavailable rather than partially rendered.
**Accept:** a no-op `EchoAgent` implements the ABC and loads.
**Deps:** T-001

### T-021 · DB schema + migrations · WIP
Implement `architecture.md` §7 exactly. Alembic migration. `agent_stats` as a materialised view refreshed every 60s.
**Accept:** migration runs clean on an empty DB; hypertable created.
**Deps:** T-001

### T-022 · Run harness + receipt writer · WIP
`harness.py`: runs observe→decide→act→report, computes `data_snapshot_hash` (sha256 of canonicalised JSON of every input `decide()` consumed), persists the run, invokes the baseline runner **on the same Observation**, writes the receipt with the advantage delta.
**Accept:** `EchoAgent` produces a valid receipt with a baseline attached. Test: `decide()` called twice on a frozen Observation returns identical Decisions (purity test — `spec.md` §11.3).
**Deps:** T-020, T-021

### T-023 · Baseline runners · WIP
`baselines.py`: `hodl`, `static_range`, `top_headline_apr`, `no_action`, `manual_analyst` (reads `fixtures/manual_baselines.json`).
**Accept:** each runs against a fixed Observation and returns a comparable metric in the agent's declared unit.
**Deps:** T-022, T-012

### T-024 · Tier enforcement · WIP
`ExecContext` with `tier` and `signer`. Tier 0/1 construct with `signer=None`; any signing attempt raises `TierViolation`.
**Accept:** test asserts Tier 0 and Tier 1 cannot sign (`spec.md` §11.4).
**Deps:** T-022

---

## Phase 3 — Tier 0 agents (ship first: they are the judge's entry point)

### T-030 · Anvil fork simulation harness · WIP — **highest value per hour in the build**
`services/agents/bsc_sentry/fork.py`: fork BSC at head, fund a fresh EOA from an impersonated whale, buy token via router, attempt sell, compare against QuoterV2. Return traces and amounts.
**Accept:** correctly identifies a known honeypot as unsellable and a known-good token as sellable. Both cases in the test suite with the addresses cited.
**Deps:** T-010, T-001

### T-031 · `bsc-sentry` full check suite · WIP
All checks in `spec.md` §3.1, scoring per §3.3. Every score line carries its evidence — never emit a score without it.
**Accept:** produces a full report for a known-good and a known-bad token; hard-fail list forces CRITICAL.
**Deps:** T-030

### T-032 · Security test set + measured claim · WIP
Build `fixtures/security_testset.json` (~150 bad from public rug post-mortems with source URLs, ~150 good). Run sentry over it. Record precision, recall, FPR, n.
**Do not train a classifier on this set — it is a test set (spec §3.4).**
**Accept:** measured numbers written to `fixtures/security_results.json` and surfaced on the agent card.
**Deps:** T-031

### T-033 · `pcs-yield` · TODO
Net-APR model per `spec.md` §4.1 with each term displayed separately. Sentry gate per §4.2 with a visible "excluded by security agent" section.
**Accept:** ranks ≥20 real PCS pools; at least one pool visibly excluded by sentry; each ranking shows the full subtraction from headline to net.
**Deps:** T-031, T-012, T-023

---

## Phase 4 — Trading agents

### T-040 · `bnb-grid` Tier 1 (paper) · WIP — **START RUNNING BY END OF DAY 2**
Calibration per `spec.md` §5.1, paper ledger with live prices and a slippage haircut, circuit breaker per §5.3. Deploy it running continuously the moment it works — the live window length cannot be bought back later.
**Accept:** runs continuously ≥6h without crashing, produces receipts against the `hodl` baseline, reports win rate / n_trades / window / max drawdown.
**Deps:** T-022, T-023, T-012

### T-041 · `bnb-grid` Tier 2 (live) · TODO
Generate a Hummingbot grid controller config, POST it via the Hummingbot API, start the bot, poll status. Small real capital.
**Accept:** a live bot places and fills at least one real order; receipt reflects real gas and fees.
**Deps:** T-040, T-004

### T-042 · `pcs-rebalancer` Tier 1 · WIP
Range selection §6.1 and the cost-aware rebalance rule §6.2. The "holding — rebalance not economic, $X cost vs $Y expected" path must be implemented and visible, not just the act path.
**Accept:** paper position tracks a real pool for ≥6h; both the rebalance and the decline-to-rebalance branches are exercised in tests.
**Deps:** T-022, T-023, T-012

### T-043 · `pcs-rebalancer` Tier 2 · WIP
Execution via `NonfungiblePositionManager` (viem) or Gateway, per the T-004 finding.
**Accept:** opens, adjusts, and closes a real small position on BSC; gas recorded from the receipts.
**Deps:** T-042, T-004

### T-044 · `venus-guard` · TODO
On-chain HF monitoring, vol-scaled trigger §7.2, buffer repayment §7.3, and the `no_action` replay baseline §7.4 that computes the liquidation penalty avoided.
**Accept:** correctly computes HF for a real Venus account; the replay baseline reproduces a historical liquidation on a known liquidated account.
**Deps:** T-022, T-023, T-010

---

## Phase 5 — Marketplace front end

### T-050 · API client + layout · TODO
Typed client in `apps/web/lib/api.ts`. Shell, nav, `config/brand.ts`.
**Deps:** T-060

### T-051 · Landing · TODO
Four equal-weight category tiles, live activity ticker of real runs, primary CTA "Try an agent — no wallet needed" deep-linking to `bsc-sentry` with a prefilled example address.
**Accept:** someone who has never seen the project reaches a real sentry result in under 2 minutes, unaided. Test this on an actual human.
**Deps:** T-050, T-031

### T-052 · Category list + compare · TODO
Filter, sort, 2–3 way compare with aligned rows. Cards render `n` and window beside every performance number; agents with no runs show "No runs yet" (R2).
**Deps:** T-050

### T-053 · Agent detail · TODO
Params with manifest defaults, the two curves (agent vs baseline, same axes, window labelled), receipt feed, risk disclosure block, security-audited badge where applicable.
**Deps:** T-050

### T-054 · Hire flow + live run view · TODO
Three steps max. Tier 2 shows the permission diff and spend cap before signing; Tier 0/1 state "no funds at risk". SSE live view with phase labels. No dead ends — every error offers a next action.
**Deps:** T-053, T-061

---

## Phase 6 — Orchestrator API, anchor, report

### T-060 · REST endpoints · TODO
All of `spec.md` §8 except the SSE stream. `/healthz` reports each dependency individually.
**Deps:** T-022, T-021

### T-061 · Hire jobs + SSE · TODO
arq queue, `POST /hires`, `GET /hires/{id}/stream`, cancel.
**Accept:** a hire runs end to end and streams phase updates to a browser.
**Deps:** T-060

### T-062 · ReceiptAnchor.sol + batching · WIP (anvil-proven; mainnet anchor pending funds)
Foundry contract per `architecture.md` §12. Orchestrator batches leaves every 10 min, submits the root. Client-side merkle proof verifier on `/receipt/[id]`.
**Accept:** at least one batch anchored on BSC mainnet; a proof verifies in the browser against the on-chain root.
**Deps:** T-060
**Done:** `anchor.py` (create_batch/submit_batch, sorted-pair keccak `merkle_root`/`merkle_proof` incl. odd-tail self-sibling, `verify_proof`, `proof_for`), `ANCHOR_ABI`; `scripts/anchor_receipts.py` proves deploy → `anchor()` → `BatchAnchored` → browser-shaped proof end to end on a local anvil (13-leaf batch, event root == batch root, proof verifies). `tests/test_anchor.py` 10 pass. Web `MerkleVerifier.tsx` (@noble/hashes keccak_256 re-fold) on `/receipt/[id]`, `next build` green.
**Blocked:** BSC-mainnet anchor needs `ANCHOR_PRIVATE_KEY` + BNB for gas (same funds gate as T-041/T-043).

### T-063 · Agent Advantage Report · TODO
`/report` generated from receipts, plus PDF export. ≥3 both-ways tasks with real attached outputs, ≥1 trading/security. Any backtest labelled `BACKTEST` with its replay method stated — never silently mixed with live runs.
**Accept:** the four tasks in `spec.md` §10 render with real data, explicit `n`, and window lengths.
**Deps:** T-032, T-040, T-042, T-033

---

## Phase 7 — Ship

### T-070 · Deploy · TODO
Front end to Vercel, orchestrator + runtime to a VPS or AWS. Public URL. `/healthz` green.
**Accept:** the site is reachable from a phone on cellular data, cold, with no VPN.

### T-071 · Full acceptance pass · TODO
Walk every item in `spec.md` §11 and record pass/fail honestly in `docs/acceptance.md`. A failure recorded is worth more than a pass faked.

### T-072 · Demo rehearsal · TODO
Rehearse the 90-second path cold, three times: land → sentry (no wallet) → yield with the sentry exclusion visible → grid receipt with drawdown → anchored proof. Time it.

---

## Suggested day mapping

| Day | Focus |
|---|---|
| 1 | T-001..T-004 (ground truth), T-020, T-021 |
| 2 | T-010..T-012, T-022..T-024, T-030 · **T-040 running live by end of day** |
| 3 | T-031..T-033, T-042, T-060 |
| 4 | T-041, T-043, T-044, T-061 |
| 5 | T-050..T-054, T-062 |
| 6 | T-063, T-070..T-072 |

## Critical path

`T-002 → T-003 → T-010 → T-011 → T-012 → T-022 → T-023 → agents → T-063`

Two things that cannot be recovered if they slip:
1. **T-040 running live by end of day 2** — window length is not purchasable later.
2. **T-004 on day 1** — discovering Gateway is quote-only on day 4 costs you the rebalancer.
