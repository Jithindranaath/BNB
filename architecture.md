# architecture.md

> Read after `context.md`. Describes *how the system is built*.
> Behavioural detail lives in `spec.md`. Task order lives in `plan.md`.

---

## 1. Layers

```
┌──────────────────────────────────────────────────────────┐
│  apps/web        Marketplace front end (Next.js, Vercel) │
│                  discover · compare · hire · watch       │
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
│  packages/data     ingestion + cache (shared)            │
│  Binance · PCS subgraph · BSC RPC · Venus · DefiLlama    │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  BNB Chain: PancakeSwap v3 · Venus · Anvil fork (sim)    │
└──────────────────────────────────────────────────────────┘
```

Hires flow down. Receipts flow back up and are written by the orchestrator, never by an agent directly. An agent returns a result object; the harness turns it into a receipt.

## 2. Repo layout

```
proofstand/
├── context.md  architecture.md  spec.md  plan.md
├── apps/
│   └── web/                    Next.js 15 App Router
│       ├── app/                routes (see spec.md §7)
│       ├── components/
│       ├── lib/api.ts          typed client for orchestrator
│       └── config/brand.ts     product name lives here ONLY
├── services/
│   ├── orchestrator/
│   │   ├── main.py             FastAPI app
│   │   ├── registry.py         loads + validates manifests
│   │   ├── harness.py          observe→decide→act→report + receipts
│   │   ├── baselines.py        counterfactual runners
│   │   ├── jobs.py             arq queue
│   │   ├── db.py               SQLAlchemy models
│   │   └── anchor.py           merkle batching → ReceiptAnchor
│   └── agents/
│       ├── base.py             Agent ABC — every agent implements this
│       ├── pcs_rebalancer/
│       ├── bnb_grid/
│       ├── pcs_yield/
│       ├── venus_guard/
│       └── bsc_sentry/
├── packages/
│   └── data/
│       ├── reference/          addresses.json, tokens.json, abis/
│       ├── sources/            binance.py subgraph.py rpc.py venus.py llama.py bscscan.py
│       ├── cache.py            parquet on disk + redis hot cache
│       ├── calibrate.py        atr(), realized_vol(), fee_apr(), il_estimate()
│       └── cli.py              `python -m data pull --pair BNB-USDT --days 30`
├── contracts/
│   ├── src/ReceiptAnchor.sol
│   └── test/
├── fixtures/                   labeled security test set; DEMO-badged only
├── scripts/
│   ├── verify_reference.ts     R1 enforcement — must pass before mainnet
│   └── probe/                  one-off API shape probes (R5)
└── infra/
    ├── docker-compose.yml      postgres, redis, hummingbot-api, gateway, anvil
    └── .env.example
```

## 3. Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| Front end | Next.js 15 App Router, React 19, Tailwind, shadcn/ui | Vercel deploy, judges need a public URL |
| Wallet | wagmi 2.x + viem 2.x + RainbowKit | Standard BSC support |
| Orchestrator | Python 3.11, FastAPI, Pydantic v2 | Hummingbot skills are Python; no FFI boundary |
| Queue | arq (Redis) | Lighter than Celery, async-native |
| DB | Postgres 16 + TimescaleDB extension | Receipts are time series |
| Cache | Redis 7 (hot) + parquet on disk (cold) | Klines cached to disk survive restarts |
| Agent runtime | Hummingbot API + Gateway via docker | Proven trading infra, not ours to write |
| Chain reads | viem multicall (TS) / web3.py (Py) | Batch or you will rate-limit |
| Simulation | Foundry Anvil, BSC fork | Honeypot detection — see spec.md §5.5 |
| Contracts | Foundry | ReceiptAnchor only |

**§ Versions** — resolved on first install (rule R4). Updated T-001, 2026-09-07.

Toolchain (host):
```
python:      3.11.9   (py -3.11; venv at .venv)
node:        24.12.0
npm:         11.6.2
docker:      29.2.0
foundry:     1.8.1    (anvil + forge, commit 982849d3140c01fd3b72905759581a132df7aa98)
```

Front end (`apps/web/package.json`):
```
next:            15.5.25   (15.1.6 pulled first, swapped for CVE-2025-66478; 15.x per spec)
react:           19.0.0
react-dom:       19.0.0
tailwindcss:     3.4.17
typescript:      5.7.3
postcss:         8.5.28    (npm override — forces it under next too; audit clean)
viem:            not yet installed — added in T-050 (scripts/ pins viem ^2.21.54 for T-002)
wagmi:           not yet installed — added in T-050
rainbowkit:      not yet installed — added in T-050
```

Orchestrator + data (`.venv`, from `pyproject.toml`):
```
fastapi:         0.141.1
uvicorn:         0.52.4
pydantic:        2.13.5
pydantic-settings: 2.15.0
sse-starlette:   3.4.11
sqlalchemy:      2.0.52
alembic:         1.19.2
psycopg:         3.3.5   (psycopg-binary 3.3.5)
arq:             0.28.0
redis (py):      5.3.1
web3.py:         8.0.0
httpx:           0.28.1
pandas:          3.0.5
pyarrow:         25.0.1
tenacity:        9.1.4
pyyaml:          6.0.3
fpdf2:           2.8.8   (added T-063 — GET /report/advantage.pdf; pure-Python, no system libs)
pytest:          9.1.1   (pytest-asyncio 1.4.0)
ruff:            0.16.6
```

Infra images (`infra/docker-compose.yml`):
```
postgres:                 timescale/timescaledb:2.17.2-pg16
redis:                    redis:7.4-alpine
anvil:                    ghcr.io/foundry-rs/foundry:v1.8.1
gateway image tag:        hummingbot/gateway:version-2.16.0  (probed in T-004; tag is "version-2.16.0", not "2.16.0")
hummingbot-api image tag: not yet pulled — T-041 (compose profile "trading")
```

## 4. Reference data — the R1 boundary

`packages/data/reference/addresses.json` is the **only** place addresses exist. Shape:

```json
{
  "bsc": {
    "chainId": 56,
    "contracts": {
      "pancakeV3Factory":            { "address": "0x…", "verified": false, "source": "https://developer.pancakeswap.finance/…" },
      "pancakeV3PositionManager":    { "address": "0x…", "verified": false, "source": "…" },
      "pancakeSmartRouter":          { "address": "0x…", "verified": false, "source": "…" },
      "pancakeQuoterV2":             { "address": "0x…", "verified": false, "source": "…" },
      "venusComptroller":            { "address": "0x…", "verified": false, "source": "…" },
      "multicall3":                  { "address": "0x…", "verified": false, "source": "…" }
    }
  }
}
```

**Do not populate these from memory.** Task T-002 in `plan.md` is: open the official docs, copy each address, paste the doc URL into `source`, run `verify_reference.ts` (which checks the address has bytecode on-chain and, where applicable, calls a known method to confirm the contract type), then flip `verified: true`.

Same pattern for `subgraphs.json`:

```json
{
  "pancakeswapV3Bsc": {
    "id": "78EUqzJmEVJsAKvWghn7qotf9LVGqcTQxJhT5z84ZmgJ",
    "gateway": "https://gateway.thegraph.com/api/{GRAPH_API_KEY}/subgraphs/id/{id}",
    "verified": false,
    "note": "ID sourced from The Graph explorer. CONFIRM in explorer before use; decentralised network, not hosted service."
  }
}
```

## 5. Data sources

| Source | Auth | Used for | Rate limit strategy |
|---|---|---|---|
| Binance `/api/v3/klines` | none | OHLCV for all calibration + trading baselines | 1000 candles/call, cache to parquet, refetch only tail |
| PCS v3 subgraph | Graph API key (free) | pools, poolDayDatas, ticks, positions | batch queries, 60s redis TTL |
| BSC RPC (Ankr/Nodereal/PublicNode) | key optional | live pool state, positions, Venus reads | **multicall always**, never loop single calls |
| Venus subgraph + direct reads | none / RPC | lending positions | act only on on-chain reads; subgraph lag can liquidate someone |
| DefiLlama `/pools`, `/chart/{pool}` | none | TVL + APR history, independent cross-check | 5 min TTL |
| BscScan API | free key, 5 req/s | verified source, contract age | token bucket at 4 req/s |

**Data classes** (see `context.md` §Glossary — this is calibration, not training):

- *Reference*: static JSON, loaded once. Addresses, decimals, tick spacings, ABIs.
- *Live state*: polled 5–30s. slot0, liquidity, position ticks, balances, HF, gas.
- *Historical*: 30–90d rolling. Klines, poolDayDatas, APR history. Powers calibration **and** baselines.

## 6. Data flow of a hire

```
1. User picks agent + config in UI
2. POST /hires → orchestrator validates config against manifest.inputs schema
3. Job enqueued (arq). Job id returned. UI subscribes to SSE /hires/{id}/stream
4. Harness:
     observe()  → packages/data pulls every input, records data_snapshot_hash
     decide()   → deterministic policy → Decision object
     act()      → Tier 0: none. Tier 1: paper ledger. Tier 2: signed tx via session key
     report()   → Result object
5. Baseline runner executes the SAME task with the SAME data_snapshot, baseline policy
6. Orchestrator writes Receipt {agent result, baseline result, advantage delta}
7. Receipt appended to merkle batch; anchored to BSC every N minutes
8. UI streams status; on completion renders result + advantage + receipt link
```

`data_snapshot_hash` is the sha256 of the canonicalised JSON of every input the decision consumed. It is what makes a receipt auditable rather than decorative: it proves the decision was made on the data we claim.

## 7. Database schema

```sql
CREATE TABLE agents (
  id TEXT PRIMARY KEY, category TEXT NOT NULL, manifest JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE runs (
  id UUID PRIMARY KEY,
  agent_id TEXT REFERENCES agents(id),
  kind TEXT NOT NULL CHECK (kind IN ('agent','baseline')),
  pair_run_id UUID,                    -- links agent run ↔ its baseline run
  tier SMALLINT NOT NULL,
  task_hash TEXT NOT NULL,
  status TEXT NOT NULL,                -- queued|running|ok|failed|halted
  started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ,
  wall_seconds NUMERIC,
  gas_wei NUMERIC DEFAULT 0,
  protocol_fees_usd NUMERIC DEFAULT 0,
  agent_fee_usd NUMERIC DEFAULT 0,
  inputs JSONB NOT NULL,
  outputs JSONB,
  output_uri TEXT,
  data_snapshot_hash TEXT NOT NULL,
  error TEXT
);
SELECT create_hypertable('runs','started_at');

CREATE TABLE receipts (
  id UUID PRIMARY KEY,
  agent_run_id UUID REFERENCES runs(id),
  baseline_run_id UUID REFERENCES runs(id),
  metric TEXT NOT NULL, unit TEXT NOT NULL,
  agent_value NUMERIC NOT NULL, baseline_value NUMERIC NOT NULL,
  delta NUMERIC NOT NULL,
  merkle_leaf TEXT NOT NULL,
  batch_id UUID, anchored_tx TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agent_stats (            -- materialised view, refreshed every 60s
  agent_id TEXT PRIMARY KEY,
  n_runs INT, window_days NUMERIC,
  median_wall_seconds NUMERIC,
  win_rate NUMERIC,                   -- fraction of receipts with delta > 0
  median_delta NUMERIC, worst_delta NUMERIC,
  max_drawdown_pct NUMERIC,           -- trading agents only, else NULL
  updated_at TIMESTAMPTZ
);
```

`agent_stats` is what the marketplace cards read. **Every card must render `n_runs` and `window_days` next to any performance number** (context.md §3.2).

## 8. Agent interface — every agent implements exactly this

```python
# services/agents/base.py
class Agent(ABC):
    manifest: Manifest                     # loaded from manifest.yaml

    @abstractmethod
    def observe(self, inputs: dict) -> Observation: ...
        # pulls ALL data via packages/data. No network calls elsewhere.
        # returns Observation(data: dict, snapshot_hash: str)

    @abstractmethod
    def decide(self, obs: Observation) -> Decision: ...
        # PURE FUNCTION. no I/O, no randomness, no clock reads.
        # same Observation must always yield the same Decision.

    @abstractmethod
    def act(self, d: Decision, ctx: ExecContext) -> Actions: ...
        # ctx.tier gates capability. ctx.signer is None for tier 0 and 1.

    @abstractmethod
    def report(self, d: Decision, a: Actions) -> Result: ...
```

`decide()` being pure is load-bearing: it is what lets the baseline runner replay the identical observation through a different policy, which is the whole measurement story. Enforce with a test that calls `decide()` twice on a frozen Observation and asserts equality.

## 9. Baselines

Each manifest names one `baseline` id. Implemented in `services/orchestrator/baselines.py`:

| Baseline id | Policy | Used by |
|---|---|---|
| `hodl` | Hold the initial basket, no action | `bnb-grid` |
| `static_range` | Open one full-range LP position, never touch | `pcs-rebalancer` |
| `top_headline_apr` | Pick highest advertised APR pool, no risk adjustment | `pcs-yield` |
| `no_action` | Do nothing; replay price history, compute liquidation if HF < 1 | `venus-guard` |
| `manual_analyst` | Human timing recorded offline; stored, not computed | `bsc-sentry` |

`manual_analyst` is the one baseline a human produces. Record it in `fixtures/manual_baselines.json` with the stopwatch time and the human's output attached. That is legitimate measured data — label it clearly as human-produced.

## 10. Tiers

| Tier | Wallet | Funds | Signer in scope | Agents |
|---|---|---|---|---|
| 0 | none | none | **never constructed** | `pcs-yield`, `bsc-sentry` |
| 1 | optional | none | **never constructed** | grid, rebalancer, venus-guard (paper) |
| 2 | required | user's own | session key, scoped | grid, rebalancer, venus-guard (live) |

Tier 0/1 safety is enforced by construction: `ExecContext.signer` is `None` and `act()` raises if it attempts to sign. Add a test asserting this.

## 11. Session keys (Tier 2)

User keeps funds in their own wallet/smart account. Agent receives a key scoped to:
`{router_address, pool_address, spend_cap_usd, expiry_ts, allowed_selectors[]}`.
UI renders the permission diff before signing. One-click revoke from the agent detail page. No `transferFrom` to arbitrary addresses is ever in `allowed_selectors`.

## 12. ReceiptAnchor.sol

Minimal by design:

```solidity
contract ReceiptAnchor {
    event BatchAnchored(uint256 indexed batchId, bytes32 root, uint256 count, uint256 ts);
    function anchor(uint256 batchId, bytes32 root, uint256 count) external onlyWriter;
}
```

Orchestrator batches receipt leaves every 10 minutes, computes the root, submits. UI shows the tx link and a client-side merkle proof verifier per receipt. This is what turns "trust our dashboard" into "verify the hash" — cheap on BSC, disproportionately valuable to the score.

## 13. Known risks — track these, do not assume them away

| Risk | Detection | Fallback |
|---|---|---|
| ~~Hummingbot Gateway may be quote-only for PancakeSwap~~ **RESOLVED T-004: Gateway v2.16.0 has PancakeSwap CLMM write routes for BSC** (open/add/remove/close/collect). Remaining risk: not yet run end-to-end on mainnet; stock image needs BSC RPC config. | T-004 done; T-043 does the real on-chain dry run | Primary = Gateway CLMM routes; fallback = our viem `NonfungiblePositionManager` path (spec §6.3), kept until Gateway proven in T-043. See docs/findings/T-004.md |
| Graph subgraph ID or gateway URL wrong/stale | `verify_reference.ts` + probe | PancakeSwap's own hosted API; direct RPC reads |
| RPC rate limits under polling load | 429s in logs | multicall + increase poll interval + second provider |
| Grid agent has too short a live window by judging | Start it running on **day 2**, not day 4 | Clearly labelled backtest alongside the live window, never instead of it |
| Four categories become four codebases | Time overrun in phase 4 | The shared harness in §8 is what prevents this — do not let an agent bypass it |
