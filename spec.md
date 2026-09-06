# spec.md

> Read after `architecture.md`. Defines *what each piece does*, precisely.
> Structural decisions live in `architecture.md`. Do not restate them here.

---

## 1. Agent manifest schema

One `manifest.yaml` per agent directory. The marketplace renders **only** from this plus `agent_stats`.

```yaml
id: pcs-rebalancer
name: PancakeSwap v3 range manager
category: rebalancing            # rebalancing|grid|yield|health_factor|security
one_liner: Keeps your LP position in range only when the fees pay for the gas.
tiers: [1, 2]
inputs:
  pool:        { type: address, required: true }
  capital_usd: { type: number, min: 50, max: 100000, required: true }
  risk:        { type: enum, values: [tight, balanced, wide], default: balanced }
data_deps: [pcs_subgraph.pool, pcs_subgraph.poolDayDatas, rpc.slot0, rpc.position, binance.klines]
baseline: static_range
advantage_metric: { name: net_fees_usd, unit: USD, higher_is_better: true }
pricing: { model: perf_fee, bps: 1000 }
kill_switch: { max_loss_pct: 5 }
```

Validate on load with Pydantic. A manifest that fails validation makes the agent unavailable — never render a partially-valid agent.

## 2. Calibration functions — `packages/data/calibrate.py`

Pure functions over real data only (rule R3). Each returns a value plus the inputs that produced it, for the snapshot hash.

```python
def atr(klines, period=14) -> float
    # Wilder ATR on 1h candles.

def realized_vol(klines, window_hours=720) -> float
    # stdev of log returns, annualised. 30d default.

def fee_apr(pool_day_datas, days=30) -> float
    # sum(feesUSD[-days:]) / mean(tvlUSD[-days:]) * 365/days

def il_estimate(vol_annual, horizon_days, range_width_pct) -> float
    # For a v3 range position. Use the standard v3 IL formula for a
    # bounded range under a lognormal price assumption. Document the
    # formula inline with its assumptions. Report as expected loss %.

def gas_cost_usd(op: str) -> float
    # From live gas price × measured gas units per op.
    # Measure gas units empirically on the Anvil fork — do NOT hardcode a guess.
```

`gas_cost_usd` must derive from a measured fork run, not an assumed constant. Record the measurement in `fixtures/gas_units.json` with the block it was measured at.

---

## 3. Agent: `bsc-sentry` (security, Tier 0) — BUILD FIRST

**Input:** `{ target: address }` (token or v3 pool).
**Output:** a scored report with per-check evidence and links.

### 3.1 Checks

| Check | Method | Evidence emitted |
|---|---|---|
| Honeypot | Anvil fork sim: fund account → buy via router → attempt sell | tx traces, tokens out vs expected |
| Transfer tax | Same sim: measure buy-in vs balance, sell-out vs quote | buy tax %, sell tax % |
| Upgradeable proxy | EIP-1967 implementation + admin slot reads | slot values, admin address |
| Dangerous functions | Scan verified ABI for mint/pause/blacklist/setFee/ownerWithdraw | matched selectors + source lines |
| Ownership | `owner()`/`getOwner()`; is it renounced, an EOA, or a timelock? | address + code size |
| LP lock | Locker contract balances + unlock timestamps for the pair's LP token | locker address, unlock ts, % locked |
| Holder concentration | Top-10 holder share excluding known burn/locker addresses | percentages |
| Contract age | Creation block from BscScan | block, date |
| Source verified | BscScan verification status | yes/no |

### 3.2 Fork simulation harness — the highest-value component

```
anvil --fork-url $BSC_RPC --fork-block-number <head>
→ impersonate a whale, transfer WBNB to a fresh EOA
→ approve router, swapExactTokensForTokens WBNB→TOKEN, record received
→ approve router, swapExactTokensForTokens TOKEN→WBNB, record received
→ compare against QuoterV2 expectation
```

Sell reverts → honeypot. Sell returns materially less than quoted → tax. This cannot be faked and no static analysis matches it. Budget real time here.

### 3.3 Scoring

Weighted rule score 0–100 with a hard-fail list (honeypot, sell tax > 25%, unrenounced mint) that forces `CRITICAL` regardless of other scores. Every score line carries its evidence. **Never output a score without the evidence that produced it.**

### 3.4 Measured claim (this is the TermiX 30% evidence)

Assemble `fixtures/security_testset.json`: ~150 known-bad BSC tokens from public rug post-mortems and incident databases, ~150 known-good established tokens. Each entry: `{address, label, source_url}`.

Run sentry over the set. Publish **precision, recall, false-positive rate, and n** on the agent card. Do **not** train a classifier on this set — it is a test set. A rule engine with evidence is both more honest and more useful to a user than an unexplainable score.

### 3.5 Baseline

`manual_analyst`: a teammate audits the same N tokens by hand with BscScan, stopwatch running. Record time and their written output in `fixtures/manual_baselines.json`. Advantage metric: `wall_seconds` (lower is better) plus a qualitative diff of findings.

---

## 4. Agent: `pcs-yield` (yield optimisation, Tier 0)

**Input:** `{ capital_usd, risk: conservative|balanced|degen, horizon_days }`
**Output:** ranked pool list with net-APR breakdown.

### 4.1 The differentiator — net APR, not headline APR

```
net_apr = fee_apr
        + emission_apr × decay_factor(horizon_days)
        − expected_il(vol_annual, horizon_days, range_width)
        − amortised_gas(entry+exit, capital_usd, horizon_days)
        − dilution_adjustment(tvl_trend)
```

Each term is displayed separately in the UI. Showing `headline 240% → net expected 31%` with the subtraction visible is exactly the "beyond basic counts" the main-track data-quality criterion asks for.

`dilution_adjustment`: project TVL forward from its 14-day trend; if TVL is rising fast, per-unit yield falls. Use DefiLlama TVL history.

### 4.2 Sentry gate

Before any pool enters the ranking, call `bsc-sentry` on both tokens and the pool. Any `CRITICAL` → excluded, and it appears in a visible "excluded by security agent" section with the reason. **This composition is a required demo beat.**

### 4.3 Baseline

`top_headline_apr`: rank by advertised APR only. Advantage metric: `net_apr_delta_pct`. Where the naive pick loses money, show it.

---

## 5. Agent: `bnb-grid` (grid trading, Tiers 1 & 2) — START RUNNING LIVE ON DAY 2

**Input:** `{ pair: BNB-USDT, capital_usd, grid_levels, risk }`

### 5.1 Calibration

```
spacing     = k(risk) × atr(klines_1h, 14) / mid_price      # k: tight .5, balanced 1.0, wide 1.75
upper/lower = 90th/10th percentile of close over 30d
levels      = clamp(user_levels, 5, 30)
size/level  = capital_usd / levels
```

### 5.2 Execution

Tier 1: paper ledger, live prices, simulated fills at the level price with a configurable slippage haircut. Tier 2: Hummingbot grid controller via the Hummingbot API — generate the controller config, POST it, start the bot, poll status. Follow the pattern in the `find-xemm-opps` skill (`--create-config`): scan → generate config → deploy.

### 5.3 Circuit breaker

Halt and report if unrealised loss exceeds `max_loss_pct` of capital, or if price exits the calibrated range by more than 2× spacing.

### 5.4 Baseline

`hodl`: buy the same USD notional at t0, hold to t1. Advantage metric: `net_pnl_usd` after gas and fees.

### 5.5 Required reported stats (TermiX explicitly asks for the risk taken)

`win_rate`, `n_trades`, **`window_days`**, `max_drawdown_pct`, `capital_at_risk_usd`, all net of gas and fees. Lead the UI with drawdown; do not bury it.

---

## 6. Agent: `pcs-rebalancer` (rebalancing, Tiers 1 & 2)

**Input:** `{ pool, capital_usd, risk }`

### 6.1 Range selection

```
half_width = m(risk) × realized_vol(klines, 30d) × sqrt(horizon_days/365)
           # m: tight 0.75, balanced 1.25, wide 2.0
ticks      = snap_to_spacing(price ± half_width, fee_tier_spacing)
```

### 6.2 Cost-aware rebalance rule — the actual intelligence

Do **not** rebalance merely because the position went out of range. Rebalance only when:

```
expected_fees(next_horizon, new_range) − realised_il_on_close − gas_cost(close+open) > 0
```

Otherwise hold and report "holding: rebalance not economic, would cost $X vs $Y expected". Surfacing the *decision not to act*, with the arithmetic, is a strong UI moment and it is genuinely better behaviour.

### 6.3 Execution

Tier 2 goes through `NonfungiblePositionManager` (`decreaseLiquidity` → `collect` → `burn` → `mint`) via viem, **unless** T-004 proves Gateway supports PancakeSwap writes.

### 6.4 Baseline

`static_range`: one full-range position at t0, untouched. Advantage metric: `net_fees_usd` (fees earned − gas − realised IL).

---

## 7. Agent: `venus-guard` (health factor, Tiers 1 & 2)

**Input:** `{ account, trigger_hf, buffer_token, buffer_amount }`

### 7.1 Monitoring

Poll `Comptroller.getAccountLiquidity` + per-vToken borrow/supply balances every 30s. Compute HF from collateral factors. **Act only on on-chain reads** — subgraph lag can get a user liquidated.

### 7.2 Buffer sizing

```
trigger_hf = 1 + z × realized_vol(collateral, 30d) × sqrt(response_window_hours/8760)
```
so the buffer scales with how violent the collateral is, rather than a fixed 1.2.

### 7.3 Action

On `HF < trigger_hf`: repay from the pre-approved buffer, smallest repayment that restores `HF ≥ target`. Alert always, even when no action is taken.

### 7.4 Baseline

`no_action`: replay the account against real price history; if HF crossed 1, compute the liquidation penalty that would have been paid. Advantage metric: `usd_saved`. This is the most dramatic receipt in the whole marketplace — build the replay carefully.

---

## 8. Orchestrator API

All responses JSON. Errors: `{ error: { code, message, detail? } }`.

```
GET  /agents                       → [AgentCard]  (manifest + agent_stats joined)
GET  /agents/{id}                  → AgentDetail  (+ recent receipts, curves)
GET  /agents/{id}/receipts?limit=  → [Receipt]
GET  /categories                   → [{ category, agent_count, live_runs }]

POST /hires                        → { hire_id, run_id }
      body: { agent_id, tier, inputs }
      422 if inputs fail manifest schema — return per-field errors
GET  /hires/{id}                   → { status, result?, receipt? }
GET  /hires/{id}/stream            → SSE: {phase, message, pct, partial?}
POST /hires/{id}/cancel            → halts the run

GET  /receipts/{id}                → Receipt + merkle proof + anchor tx
GET  /report/advantage             → the Agent Advantage Report payload
GET  /report/advantage.pdf         → rendered PDF

GET  /healthz                      → { db, redis, rpc, hummingbot, gateway }
```

`/healthz` must report each dependency individually. During judging you need to know within seconds which leg is down.

## 9. Front end

### 9.1 Routes

```
/                       landing: 4 category tiles + live activity ticker
/category/[slug]        agent list, filter + sort, compare checkboxes
/agent/[id]             detail: what it does, params, curves, receipt feed, Hire
/hire/[id]              live run view (SSE), then result
/receipt/[id]           full receipt + merkle proof verifier
/report                 the Agent Advantage Report, public
```

### 9.2 Landing requirements

Four category tiles, equal visual weight (main-track diversity criterion — this is literally scored). Live ticker of real recent runs. One primary CTA: **"Try an agent — no wallet needed"** → deep-links to `bsc-sentry` with a prefilled example address. A judge must reach a real result from a cold landing in under 2 minutes with zero instructions.

### 9.3 Agent card — required fields

Name, category, one-liner, tier badges, price, and:
`advantage vs baseline · n=<runs> · <window> days · median <time>`
plus `max drawdown` for trading agents. **Never render a performance number without `n` and window beside it.** An agent with no runs shows "No runs yet", never an estimate.

### 9.4 Compare

Select 2–3 agents in a category → aligned attribute rows, same labels in the same order. Same-category only.

### 9.5 Hire flow — 3 steps maximum

1. Configure — every field pre-filled with a sane default from the manifest
2. Review — for Tier 2, the permission diff and spend cap; for Tier 0/1, "no funds at risk" stated plainly
3. Run — live SSE view with phase labels

No dead ends. Every error state offers a next action.

### 9.6 Agent detail — the two curves

Agent equity/value curve and baseline curve on the same axes, same window, with the window length labelled on the chart. Below it, the receipt feed with the advantage delta per run.

## 10. The Agent Advantage Report

`/report` is generated from `receipts`, never hand-written. Contents:

- ≥3 tasks run both ways, **≥1 from trading/stock/security** (we have 2: grid and sentry)
- Per task: time, cost, output quality, with actual outputs attached/linked
- Explicit `n`, window length, and methodology
- Backtests, if any, labelled `BACKTEST` with the replay method stated — never mixed silently with live runs

Planned tasks:

| # | Task | Agent | Baseline | Headline metric |
|---|---|---|---|---|
| 1 | Grid on BNB/USDT, ≥48h live, small real capital | `bnb-grid` | hodl | net PnL, win rate, **max drawdown**, window |
| 2 | Audit 10 BSC tokens | `bsc-sentry` | manual analyst, stopwatch | wall time + findings diff |
| 3 | PCS v3 LP, same pair/capital/window | `pcs-rebalancer` | static range | net fees after gas + IL |
| 4 | Yield routing | `pcs-yield` | top headline APR | net APR delta |

## 11. Acceptance criteria — definition of done

The build is done when all of these pass:

1. Cold clone → `docker compose up` → `data pull` produces a real 30d OHLCV frame in under 2 minutes.
2. `verify_reference.ts` passes; every address has `verified: true` with a source URL.
3. A test proves `decide()` is pure: same Observation → identical Decision, twice.
4. A test proves Tier 0/1 cannot sign: `ExecContext.signer is None` and any signing attempt raises.
5. All five agents complete a run and produce a receipt with a baseline attached.
6. A stranger reaches a real `bsc-sentry` result from `/` with no wallet in under 2 minutes.
7. Every performance number in the UI displays `n` and window.
8. At least one receipt batch is anchored on BSC and its merkle proof verifies client-side.
9. `/report` renders ≥3 both-ways tasks with real attached outputs, ≥1 trading/security.
10. `/healthz` reports every dependency, and the public URL is up.
