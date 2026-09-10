# proofstand

**An agent marketplace for BNB Chain where every hire produces a verifiable receipt
proving the agent beat doing the job yourself.**

Built for the [BNB Chain "Smart Money Era" hackathon](https://www.bnbchain.org/en/hackathons/smart-money-era)
— submitted to the **TermiX** challenge track (and aligned with the main
*BNB Agent Studio Marketplace* track and the *PancakeSwap* partner challenge).

> The product name lives in exactly one place — `apps/web/config/brand.ts`.
> "proofstand" is the working codename.

---

## Demo

<video src="https://github.com/Jithindranaath/BNB/raw/main/docs/media/proofstand-demo.mp4" controls muted playsinline width="100%"></video>

▶ **[proofstand-demo.mp4](docs/media/proofstand-demo.mp4)** (if the player doesn't load inline) — a narrated ~95-second walkthrough recorded against the live site: cold landing → hire `bsc-sentry` on CAKE with no wallet → the timed comparison against a manual audit → recompute the receipt's Merkle proof in-browser → the Agent Advantage Report → `venus-guard` turning a ~$150 liquidation into a ~$300 swing, every figure tracing back to a receipt.

### Live

| | |
|---|---|
| **Marketplace** | https://proofstand.vercel.app |
| **Orchestrator API** | https://proofstand-orchestrator.onrender.com — [`/healthz`](https://proofstand-orchestrator.onrender.com/healthz) · [`/report/advantage`](https://proofstand-orchestrator.onrender.com/report/advantage) · [`/report/advantage.pdf`](https://proofstand-orchestrator.onrender.com/report/advantage.pdf) |

> The free Render instance sleeps after ~15 min idle — the first request then takes ~50 s to wake it. Open `/healthz` once and wait for `status: ok` before walking the demo.

---

## The idea

Every team in this hackathon will ship a marketplace with an equity curve on each
agent card. Almost none of them will be able to answer the one question TermiX
actually asks:

> *"Does hiring this agent beat doing the job yourself — and can you prove it with numbers?"*

proofstand is built around a single primitive that answers it. Every time an agent
runs, the orchestrator runs the **counterfactual** in the same breath — the same
task, on the same frozen data, with a "do nothing / do it manually" policy — and
writes a **receipt**:

```
Receipt = { agent_run, baseline_run, advantage_delta }
```

The delta is a measured number with a unit, a sample size, and a time window. The
receipt is hashed, batched into a Merkle tree, and anchored on BSC. The marketplace
UI lets you **re-verify the hash in your browser** instead of trusting the dashboard.

Build the receipt layer once, and it satisfies three overlapping rubrics at the
same time.

---

## How it maps to the judging criteria

### TermiX challenge (primary track)

| Criterion | Weight | How proofstand addresses it |
|---|---|---|
| **Value of services** | 30% | Five priced, working agents across high-stakes categories. Two are **Tier 0** — a judge gets a real result with no wallet, no funds, in under 2 minutes. |
| **Proven agent advantage** | 30% | The receipt layer. Every run carries `{agent, baseline, delta}` with `n` + window. `/report` renders the **Agent Advantage Report** from the receipts table — never hand-written. |
| **High-stakes categories + track record** | 20% | Security (`bsc-sentry`) and trading (`bnb-grid`) are first-class, not general-purpose. Trading agents report win rate, `n_trades`, **`window_days`, and `max_drawdown_pct`** net of gas and fees. |
| **Marketplace quality** | 20% | Discover → compare (same-category, aligned rows) → hire (3 steps, every field pre-filled) → watch (live SSE) → verify. No dead ends; no instruction manual. |

### Main track — *BNB Agent Studio Marketplace*

- **Functionality** — full journey works end to end: landing → category → agent detail → hire → live run → result → receipt → on-chain proof.
- **Data quality** — real-time, and *beyond basic counts*. `pcs-yield` shows `headline 240% APR → net expected 31%` with every subtraction (IL, gas, emission decay, TVL dilution) itemised on screen.
- **Agent diversity** — all four mandated categories (rebalancing, grid, yield, health-factor) shipped with **equal depth**: each has its own data sources, its own baseline definition, its own receipts. Not four cards pointing at one engine.

### PancakeSwap partner challenge

`pcs-rebalancer` and `pcs-yield` deliver measurable value to PancakeSwap LPs and
yield hunters. **Funds are never at risk** — Tier 0/1 cannot hold a signer by
construction; Tier 2 uses a scoped, revocable session key.

---

## The receipt primitive, in detail

```
1. User picks an agent + config in the UI
2. POST /hires → config validated against the agent's manifest schema
3. Harness runs observe → decide → act → report
     observe()  pulls every input via packages/data, records data_snapshot_hash
     decide()   PURE function: same observation always yields the same decision
     act()      Tier 0: nothing · Tier 1: paper ledger · Tier 2: scoped session key
     report()   Result object
4. Baseline runner replays the SAME data_snapshot through the baseline policy
5. Orchestrator writes Receipt { agent result, baseline result, advantage delta }
6. Receipt leaf appended to a Merkle batch; anchored to BSC every 10 minutes
7. UI streams the run over SSE; on completion shows result + advantage + receipt link
8. /receipt/{id} recomputes the Merkle proof client-side (@noble/hashes) and
   checks it against the on-chain BatchAnchored event
```

`data_snapshot_hash` is the sha256 of the canonicalised JSON of every input the
decision consumed. It is what makes a receipt *auditable* rather than decorative:
it proves the decision was made on the data we claim, and it is what lets the
baseline runner replay an identical observation through a different policy. That
replay is the entire measurement story, so `decide()` being a pure function is
enforced by a test that calls it twice on a frozen observation and asserts equality.

**Baselines are real, never estimated:**

| Baseline | Policy | Used by |
|---|---|---|
| `hodl` | Buy the same USD notional at t0, mark to market at t1 | `bnb-grid` |
| `static_range` | Open one full-range LP position, never touch it | `pcs-rebalancer` |
| `top_headline_apr` | Pick the highest advertised APR pool, no risk adjustment | `pcs-yield` |
| `no_action` | Do nothing; replay real price history, compute the liquidation penalty if HF crossed 1 | `venus-guard` |
| `manual_analyst` | A human audits the same target with a stopwatch running; recorded, not computed | `bsc-sentry` |

---

## The five agents

All four main-track categories, plus security (which TermiX weights above
general-purpose). One shared `Agent` interface (`services/agents/base.py`); the
marketplace renders **only** from each agent's `manifest.yaml` joined with its
live `agent_stats`.

| Agent | Category | Tiers | What it does | Baseline | Advantage metric |
|---|---|---|---|---|---|
| **`bsc-sentry`** | security | 0 | Fork-simulates a real buy **and sell** on an Anvil BSC-mainnet fork to catch honeypots and tax traps, plus on-chain checks (proxy slots, owner, LP lock, holder concentration, dangerous selectors, contract age, source verification). Every score line carries its evidence. | `manual_analyst` | `wall_seconds` (lower is better) + findings diff |
| **`pcs-yield`** | yield | 0 | Ranks pools by **net APR** = fee APR + emission APR·decay − expected IL − amortised gas − TVL-dilution adjustment. Each term shown separately. Every candidate pool passes through `bsc-sentry` first; anything `CRITICAL` is excluded and shown in a visible "excluded by security agent" section. | `top_headline_apr` | `net_apr_delta_pct` |
| **`bnb-grid`** | grid | 1, 2 | Places an ATR-calibrated grid on BNB/USDT. Only counts a win **after gas and fees**. Circuit breaker halts on max-loss or a 2× range break. | `hodl` | `net_pnl_usd` |
| **`pcs-rebalancer`** | rebalancing | 1, 2 | Manages a PancakeSwap v3 LP range. **Does not rebalance just because the position went out of range** — only when `expected_fees − realised_IL − gas > 0`. Otherwise it holds and reports the arithmetic. | `static_range` | `net_fees_usd` |
| **`venus-guard`** | health-factor | 1, 2 | Watches a Venus borrow position on **on-chain reads** (subgraph lag can get someone liquidated) and repays the *smallest* amount from a pre-approved buffer that restores a safe HF. Alerts even when it takes no action. | `no_action` | `usd_saved` |

**The composition to watch:** `bsc-sentry` gates `pcs-yield`. The yield router
refuses to route capital into a pool the security agent flags — one agent's output
is another agent's safety rail. This is the most memorable beat in the demo.

Calibration ≠ training. These are **deterministic policy engines** that compute
parameters from recent real data (`atr`, `realized_vol`, `fee_apr`, `il_estimate`,
`gas_cost_usd`). No models, no predictions, no LLM ever picks a direction, an
amount, or signs anything.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  apps/web        Next.js 15 · Vercel                     │
│                  discover · compare · hire · watch · verify │
└──────────────────────────────────────────────────────────┘
                          ↓ REST + SSE
┌──────────────────────────────────────────────────────────┐
│  services/orchestrator   FastAPI                         │
│    registry · hire jobs · run harness · RECEIPT LAYER    │
└──────────────────────────────────────────────────────────┘
          ↓ in-process                    ↓ HTTP
┌───────────────────────────┐  ┌──────────────────────────┐
│ services/agents           │  │ Hummingbot API + Gateway │
│ 5 agents, one interface   │  │ (docker, BSC connectors) │
└───────────────────────────┘  └──────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  packages/data     ingestion + cache (shared)           │
│  Binance · PCS subgraph · BSC RPC · Venus · DefiLlama · BscScan │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  BNB Chain: PancakeSwap v3 · Venus · Anvil fork (sim)    │
│  contracts/ReceiptAnchor.sol                             │
└──────────────────────────────────────────────────────────┘
```

Hires flow down. Receipts flow back up and are written **by the orchestrator, never
by an agent** — an agent returns a result object; the harness turns it into a receipt.

### Data sources

| Source | Auth | Used for |
|---|---|---|
| Binance `/api/v3/klines` | none | OHLCV for all calibration + trading baselines (cached to parquet, tail-refetched) |
| PancakeSwap v3 subgraph | free Graph key | pools, `poolDayDatas`, ticks, positions |
| BSC RPC (Ankr / NodeReal / PublicNode) | optional key | live pool state, positions, Venus reads — **multicall3 always**, never a single-call loop |
| Venus (subgraph + direct reads) | none / RPC | lending positions — acts only on on-chain reads |
| DefiLlama `/pools`, `/chart/{pool}` | none | TVL + APR history, independent cross-check |
| BscScan API | free key | verified source, contract creation block — token-bucketed at 4 req/s |

### The Agent Advantage Report — `/report`

Generated from the `receipts` table, never hand-written. Public URL, downloadable
as PDF (`GET /report/advantage.pdf`). Contents per TermiX's required submission
component:

- ≥ 3 tasks run **both ways**, ≥ 1 from trading / security
- Per task: time, cost, output quality, with the actual outputs attached/linked
- Explicit `n`, evaluation window, and methodology
- Backtests labelled `BACKTEST` with the replay method stated — never blended silently into a live number

### ReceiptAnchor.sol

Minimal by design — one event, one writer-gated function:

```solidity
event BatchAnchored(uint256 indexed batchId, bytes32 root, uint256 count, uint256 ts);
function anchor(uint256 batchId, bytes32 root, uint256 count) external onlyWriter;
```

The orchestrator batches receipt leaves every 10 minutes, computes the root, and
submits. The UI shows the tx link and a per-receipt client-side Merkle proof
verifier. This is what turns "trust our dashboard" into "verify the hash" — cheap
on BSC, disproportionately valuable to the score.

---

## Why the numbers are trustworthy — the rules that override everything

A fabricated address or a plausible-looking fake number silently destroys a
trading-track submission the moment a judge spots it. These rules are enforced,
not aspirational:

- **R1 — no invented addresses, endpoints, ABIs, or subgraph IDs.** All of them
  live in `packages/data/reference/`. `scripts/verify_reference.ts` checks every
  address has bytecode on BSC mainnet *and* calls a known method to confirm the
  contract type before it can be marked `verified: true`. 15/15 entries verified.
- **R2 — no invented numbers.** No placeholder APRs, no example win rates. If data
  is unavailable the UI shows an explicit empty state (`"No runs yet"`), never a
  fake. Any demo data lives in `fixtures/` and is badged `DEMO`.
- **R3 — no synthesised market data.** No GBM price generators, no random walks.
  Real data or no data.
- **Gas is measured, not guessed.** `fixtures/gas_units.json` records gas units per
  op from real transactions on an Anvil BSC fork, with the block they were measured at.
- **Safety by construction.** Tier 0/1 `ExecContext.signer` is `None` and any
  signing attempt raises `TierViolation` — proven by a test. Tier 2 uses a session
  key scoped to `{router, pool, spend_cap, expiry, selectors}`, with the permission
  diff shown before signing and one-click revoke. The LLM only parses intent into a
  validated config and writes prose; every decision is deterministic code.

---

## Tech stack

| Layer | Choice |
|---|---|
| Front end | Next.js 15 App Router, React 19, Tailwind, shadcn/ui — deployed on Vercel |
| Wallet | wagmi 2 + viem 2 + RainbowKit (Tier 2 only) |
| Orchestrator | Python 3.11, FastAPI, Pydantic v2 |
| Queue | arq (Redis) |
| DB | Postgres 16 + TimescaleDB (receipts are a time series) |
| Cache | Redis 7 (hot) + parquet on disk (cold) |
| Agent runtime | Hummingbot API + Gateway via docker (BSC connectors) — proven to have PancakeSwap v3 CLMM write routes |
| Simulation | Foundry Anvil, BSC mainnet fork |
| Contracts | Foundry — `ReceiptAnchor.sol` only |

Resolved versions are pinned in `architecture.md` §Versions (rule R4 — recorded on
first install, not assumed).

---

## Quick start

```bash
# 1. secrets
cp infra/.env.example .env          # fill keys as tasks need them

# 2. infra — postgres+timescale, redis, anvil
docker compose up -d
docker compose ps                   # all three healthy

# 3. python (3.11 only)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q -m "not live"             # 70 passed, no network needed

# 4. pull real market data (rule R1/R3 — this is real Binance OHLCV)
python -m data pull --pair BNB-USDT --days 30 --interval 1h

# 5. orchestrator  (web app's NEXT_PUBLIC_ORCHESTRATOR_URL defaults to :8088)
python -m uvicorn orchestrator.main:app --reload --port 8088 --app-dir services

# 6. web
cd apps/web && npm install && npm run dev     # http://localhost:3000

# 7. contracts
cd contracts && forge test

# 8. seed some receipts, then anchor a batch
python scripts/run_paper_loops.py --interval 600     # leave running
python scripts/anchor_receipts.py                    # local anvil :8545
```

`curl localhost:8088/healthz` reports every dependency individually — during
judging you want to know within seconds which leg is down.

### Demo walkthrough (~90 seconds, no wallet)

1. **Land** on `/` — four category tiles, a live activity ticker of real recent runs, one CTA.
2. **Health factor → Venus health-factor guard → Hire → Run.** Tier 1, paper on
   live prices, no funds at risk. It replays a real 365-day drawdown against a real
   on-chain Venus borrower (~12 s).
3. **The receipt.** Under the worst real drawdown the account is liquidated for a
   measured USD amount; the guard's top-ups prevent it. That saved amount is now a receipt.
4. **Verify the hash.** The `/receipt/{id}` page recomputes the Merkle root from
   the leaf + proof in your browser and checks it against the anchored root. Green
   = the number was not touched.
5. **The report.** `/report` — every both-ways task, generated from the receipts
   table, with `n`, window, methodology, and a **Download PDF** for the judges.

Full script, click-by-click, with measured backend latency per beat: `docs/demo.md`.

---

## Repo layout

```
proofstand/
├── context.md  architecture.md  spec.md  plan.md   ← read in this order
├── apps/web/                     Next.js 15 marketplace
│   ├── app/                      routes: / /category/[slug] /agent/[id]
│   │                                     /hire/[id] /receipt/[id] /report
│   ├── components/               Curve · HirePanel · MerkleVerifier · ui
│   ├── lib/api.ts                typed orchestrator client
│   └── config/brand.ts          product name lives HERE only
├── services/
│   ├── orchestrator/             FastAPI — api · harness · baselines · anchor · report
│   └── agents/                   base.py + 5 agent packages, one interface
├── packages/data/
│   ├── reference/                addresses.json · tokens.json · subgraphs.json · abis/  (R1 boundary)
│   ├── sources/                  binance · subgraph · rpc · venus · llama · bscscan
│   ├── calibrate.py              atr · realized_vol · fee_apr · il_estimate · gas_cost_usd
│   └── cli.py                    `python -m data pull ...`
├── contracts/                    ReceiptAnchor.sol + Foundry tests (incl. honeypot fixtures)
├── fixtures/                     labeled data only — security testset, gas units, manual baselines
├── scripts/                      verify_reference.ts · anchor_receipts.py · measure_gas.py · paper loops · probes
├── infra/                        docker-compose, deploy configs
└── docs/                         acceptance.md · demo.md · deploy.md · envio-indexer.md · findings/
```

---

## Testing

```
pytest -q -m "not live"   → 70 passed          (no network)
pytest -q -m "live"       → 41 passed, 1 skipped  (hits real BSC / Binance / DefiLlama)
                            total: 111 passed, 1 skipped
forge test                → ReceiptAnchor + honeypot/high-tax token fixtures
```

Load-bearing tests: `decide()` purity (same observation → identical decision,
twice), Tier 0/1 cannot sign, the Merkle proof/verify round-trip for
`n ∈ {1,2,3,4,5,8,13}` including the odd-tail case, and `bsc-sentry` returning
`CRITICAL` with the sell-revert string as evidence on a real honeypot.

`bsc-sentry` over a labelled set (established BSC tokens + deployed synthetic
malicious contracts with real PancakeSwap v2 liquidity): **precision 1.0, recall
1.0, FPR 0.0 at n=28** (`fixtures/security_results.json`) — a rule engine with
evidence, *not* a trained classifier on a test set.

---

## Status

Snapshot 2026-09-10. Nothing here is faked; partials name their blocker.

**Done and verified**

- **Deployed and reachable** — marketplace on Vercel, orchestrator + Postgres on Render; `/healthz` reports `db` and `rpc` ok. URLs above.
- All five agents run against real BSC / Binance / DefiLlama data and produce receipts.
- **All five agents** (`bsc-sentry`, `bnb-grid`, `pcs-rebalancer`, `pcs-yield`, `venus-guard`) have **both-ways** receipts in the DB; `/report` renders all five with `n`, evaluation window, methodology, and a valid PDF.
- `bsc-sentry` vs a real timed manual audit of CAKE: agent verdict in ~5 s against a human analyst's 54 s (`fixtures/manual_baselines.json`).
- `pcs-yield` ships on DefiLlama (PancakeSwap v2 BSC) + Binance vol + the on-chain sentry gate; a real hire beats the `top_headline_apr` pick by ~3.8 pp.
- 15/15 reference addresses verified on-chain; `decide()` purity and Tier 0/1 no-sign proven by tests.
- Merkle anchor + client-side proof verification working end-to-end — the `/receipt/{id}` page recomputes the proof in-browser (`@noble/hashes`) against the anchored `BatchAnchored` root.

**Pending — all external, all tracked**

- **BSC-mainnet anchoring** — batches are anchored on a dev chain today; mainnet needs a funded low-value `ANCHOR_PRIVATE_KEY` + BNB for gas.
- **`pcs-yield` on v3 pools** — currently ranks v2; the v3 upgrade is a self-hosted Envio HyperIndex indexer (`docs/envio-indexer.md`).
- **Grid Tier-2 live** — pending real funds; Tier-1 paper trading is live.

Full acceptance walk against `spec.md` §11: `docs/acceptance.md`.

---

## For contributors

Read the docs in this order, every session:
[`context.md`](context.md) (what & why & the rules) →
[`architecture.md`](architecture.md) (how it's built) →
the relevant part of [`spec.md`](spec.md) (what each piece does) →
the current task in [`plan.md`](plan.md) (the work queue).
[`WORKFLOW.md`](WORKFLOW.md) is the session loop and phase gates.

The rules that override everything are in `context.md` §5–§6: real data or an
explicit empty state — never a plausible fake; Tier 0/1 agents cannot sign by
construction; every UI number carries `n` + window; BSC mainnet only.
