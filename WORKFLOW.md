# WORKFLOW.md

> **The process doc.** `context.md`/`architecture.md`/`spec.md` say *what* to build;
> `plan.md` says *what order* and holds task status. This file says *how we work
> each session* and *when we're allowed to move on*.
>
> This file does **not** track task status — `plan.md` owns that (rule R7, one
> source of truth). This file holds: the session loop, the phase gates, a single
> "current focus" pointer, a one-time setup checklist, and an append-only journal.

---

## 0. How to use this doc

- **Start of every session:** do §1 (the session-start ritual).
- **While working a task:** follow §2 (the task loop).
- **Before moving to the next phase:** check §3 (phase gates) — all must be true.
- **When stuck:** §4 (escalation rules). Don't thrash.
- **End of every work block:** append to §6 (the journal). One entry per session.
- **§7** is the one-time environment setup — tick it once, never again.

---

## 1. Session-start ritual (do this every time, in order)

1. Read `context.md` — the rules. If anything below contradicts it, context.md wins.
2. Read `architecture.md` — how the system is built. Check the **§Versions** block is filled.
3. Read the relevant section of `spec.md` for the task you're about to do.
4. Read `plan.md`. Find the **first** task whose `Status` is `TODO` and whose
   **Deps are all `DONE`**. That is the only task you may start.
5. Confirm the "Current focus" pointer in §5 of this file matches. If not, fix it.
6. Skim the last 2–3 entries in §6 (journal) for unfinished threads / open blockers.

**Never** start a task with an unmet dependency. **Never** work two tasks at once.

---

## 2. The task loop (per `T-0xx`)

```
  PICK        plan.md: first TODO with all deps DONE
   │
   ▼
  OPEN        set that task's Status → WIP in plan.md
   │          set §5 "Current focus" in this file → T-0xx
   │
   ▼
  UNDERSTAND  re-read the task's spec.md section + its Accept criteria
   │          list the acceptance checks as a literal checklist before coding
   │
   ▼
  BUILD       smallest change that satisfies the Accept criteria
   │          - no invented addresses / numbers / market data (R1–R3)
   │          - new constant already exists somewhere? import it (R7)
   │          - API shape unknown? probe first under scripts/probe/ (R5)
   │          - unsure it works? mark the path UNVERIFIED, say so out loud (R6)
   │
   ▼
  VERIFY      run every Accept check. Record pass/fail HONESTLY.
   │          a failing check reported > a passing check faked (context.md §9)
   │          if a check can't run yet (missing key/dep): note which, mark
   │          the task BLOCKED(reason) — do not fake around it
   │
   ▼
  RECORD      - update architecture.md §Versions if this was a first install (R4)
   │          - write any finding to docs/findings/ if the task calls for it
   │
   ▼
  COMMIT      git add -A && git commit -m "[T-0xx] <what changed>"
   │
   ▼
  CLOSE       plan.md: Status → DONE (or BLOCKED(reason))
   │          append a journal entry in §6
   │
   ▼
  STOP        stop for review. Do not roll straight into the next task
              unless the session scope explicitly said to.
```

If a task exceeds **~90 minutes of tool calls**, stop and report the blocker in
§6 instead of thrashing (context.md §9).

---

## 3. Phase gates — do not advance until every box is true

### Gate 0 → 1  (Ground truth complete)
- [ ] `docker compose up` brings postgres, redis, anvil to healthy
- [ ] `pytest` runs clean; `npm run dev` starts clean
- [ ] `npx tsx scripts/verify_reference.ts` exits 0 — **zero** `verified: false` entries
- [ ] six probe outputs on disk under `scripts/probe/output/`, each a real response
- [ ] `docs/findings/T-004.md` exists and states exactly what Gateway can/can't do
- [ ] `architecture.md` §Versions filled with resolved versions (R4)

### Gate 1 → 2  (Data layer trustworthy)
- [ ] one live unit test per source in `packages/data/sources/` passes
- [ ] cold `python -m data pull --pair BNB-USDT --days 30` < 60s; warm < 2s
- [ ] parquet cache survives a container restart
- [ ] every calibration fn tested against a hand-computed value on a fixed fixture
- [ ] `fixtures/gas_units.json` written from a **measured** Anvil fork run, with block

### Gate 2 → 3  (Scoring primitive works)
- [ ] `EchoAgent` produces a valid receipt with a baseline attached
- [ ] purity test passes: `decide()` twice on a frozen Observation → identical Decision
- [ ] DB migration runs clean on empty DB; hypertable created
- [ ] Tier 0 + Tier 1 cannot sign: `ExecContext.signer is None`, signing raises `TierViolation`
- [ ] all five baseline runners return a comparable metric in the agent's declared unit

### Gate 3 → 4  (Tier 0 agents shipped)
- [ ] fork harness flags a known honeypot unsellable + a known-good token sellable (addresses cited)
- [ ] `bsc-sentry` emits a full report; **no score line without its evidence**
- [ ] `fixtures/security_results.json` has real precision / recall / FPR / n
- [ ] `pcs-yield` ranks ≥20 real pools; ≥1 visibly excluded by the sentry gate

### Gate 4 → 5  (Trading agents live)
- [ ] **`bnb-grid` Tier 1 has been running live since end of day 2** (window can't be bought back)
- [ ] grid runs ≥6h without crashing, produces receipts vs `hodl`, reports drawdown
- [ ] `pcs-rebalancer` exercises **both** the rebalance and the decline-to-rebalance branches
- [ ] `venus-guard` reproduces a real historical liquidation on a known account

### Gate 5 → 6  (Marketplace usable)
- [ ] a cold stranger reaches a real `bsc-sentry` result from `/` in < 2 min, unaided
- [ ] every performance number in the UI renders `n` + window; no-run agents show "No runs yet"
- [ ] compare works within a category with aligned rows

### Gate 6 → 7  (Verifiable + reportable)
- [ ] `/healthz` reports every dependency individually
- [ ] ≥1 receipt batch anchored on BSC mainnet; merkle proof verifies client-side
- [ ] `/report` renders ≥3 both-ways tasks with real attached outputs, ≥1 trading/security

### Gate 7  (Ship)
- [ ] every item in `spec.md` §11 walked and recorded pass/fail in `docs/acceptance.md`
- [ ] public URL reachable from a phone on cellular, cold, no VPN
- [ ] 90-second demo path rehearsed cold three times, timed

---

## 4. Escalation rules — when to stop and ask instead of guessing

Stop and surface it (don't work around it silently) when:

- You need an **address, endpoint, ABI, or subgraph ID** that isn't in
  `packages/data/reference/` — rule R1, never guess.
- An **API key or secret** is required and not present — name the exact env var
  and the task it blocks.
- A task's **dependency isn't actually DONE** even though `plan.md` says so.
- An external service's **response shape doesn't match** what the code expects —
  probe, print, then decide.
- You're **unsure whether something works** (e.g. Gateway writes) — mark it
  `UNVERIFIED`, report the uncertainty, don't assume the happy path (R6).
- A task passes **90 minutes of tool calls** with no acceptance check green.

---

## 5. Current focus

> Exactly one line. Update it at the OPEN step of every task.

```
PHASE:  0 — Ground truth  (COMPLETE — Gate 0→1 review pending)
TASK:   T-002, T-003, T-004 all DONE
STATE:  Phase 0 done except two key-gated re-runs (subgraph, bscscan)
NEXT:   Phase 1 — T-010 source clients (binance/rpc/venus/llama unblocked now;
        subgraph.py + bscscan.py wait on GRAPH_API_KEY / BSCSCAN_API_KEY)
```

---

## 6. Session journal (append-only — newest at the bottom)

> One entry per work block. Format:
> `### <date> · <task(s)> · <outcome>` then 2–6 bullets: what changed, what
> passed/failed, what's blocked, what's next.

### 2026-09-07 · setup + T-001 · DONE
- Read all four planning docs; wrote this WORKFLOW.md.
- Environment found: Node v24.12, Docker 29.2 (daemon **not running** at start,
  started it), Python 3.12/3.13/3.14 present, **no 3.11** → installed
  `Python.Python.3.11` (3.11.9) via winget. Foundry 1.8.1 already present.
- Decisions locked with the user: target **Python 3.11**; this session covers
  **all of Phase 0 (T-001–T-004)**; API keys **not yet available**.
- T-001 built: full tree per architecture.md §2, git init, `.gitignore`,
  docker-compose (root `include:` → `infra/`), `pyproject.toml` (+ `.venv` 3.11),
  Next.js 15 app, 5 `manifest.yaml`, blank reference JSON, `verify_reference.ts`,
  `ReceiptAnchor.sol` + tests, `.env.example`, `README.md`.
- **Acceptance — all pass:**
  - `docker compose up -d` → postgres, redis, anvil all **healthy**
  - `.venv` `pytest -q` → **4 passed**
  - `npm run dev` → **Ready in 12.9s, HTTP 200**, HTML renders
  - (bonus) `forge test` → **4 passed**
- Fixes during build: `next` 15.1.6 → 15.5.25 (CVE-2025-66478); `postcss` npm
  `overrides` → 8.5.28 (clears 2 transitive advisories); prod `npm audit` clean.
- architecture.md §Versions filled with every resolved version (R4).
- Compose project name resolved to `bnb` (dir name), not `proofstand` — harmless.
- Note: the `npm run dev` smoke used `taskkill //F //IM node.exe` to stop it —
  blunt (kills all node). Use a targeted kill next time.
- Next: **T-002** — fetch PCS/Venus/Multicall3 addresses + subgraph IDs from
  official docs (R1), run `verify_reference.ts` against keyless PublicNode RPC.

### 2026-09-07 · T-002 / T-003 / T-004 · DONE (Phase 0 complete)
- **T-002:** 15 addresses+tokens sourced from official repos/docs and verified
  on BSC mainnet (bytecode + identity eth_call) — `verify_reference.ts` rewritten
  data-driven, exits 0. PancakeSwap v3 (factory/deployer/NPM/router/quoter) from
  `pancake-v3-contracts/deployments/bscMainnet.json`; SmartRouter + V2 router/factory;
  Venus Comptroller from docs-v4.venus.io; Multicall3 from mds1/multicall3; tokens
  from pancakeswap/token-list (all 18-dec on BSC). subgraphs.json: ids recorded,
  `verified:false`, deferred to T-003 (needs GRAPH_API_KEY). abis/erc20.json added.
- **T-003:** 6 probes written + run, raw output committed under scripts/probe/output/.
  OK: Binance, DefiLlama (pools+chart), BSC RPC multicall3, Venus on-chain.
  BLOCKED (recorded, not worked around): PCS subgraph (GRAPH_API_KEY), BscScan
  (BSCSCAN_API_KEY). **Finding: Venus Core Comptroller is an EIP-2535 Diamond** —
  `liquidationIncentiveMantissa()` reverts; T-044 must find the real source.
- **T-004:** **Gateway v2.16.0 CAN write to PancakeSwap v3 on BSC** (clmm routes
  open/add/remove/close/collect + swap; `bsc` supported). Verified in source +
  a live container (`/config?namespace=pancakeswap` returns real config; clmm
  route reachable). "Pool not found" for BSC = stock image has no BSC RPC (config,
  not capability). "Assume quote-only" premise retired. Primary = Gateway,
  fallback = viem NPM path, decided for real in T-043. docs/findings/T-004.md.
- Blunt-kill note from last entry still stands; not repeated this session.
- Key-gated re-runs outstanding: `probe/pcs_subgraph.ts`, `probe/bscscan_source.ts`.
- Next: **Gate 0→1 review**, then Phase 1 T-010.

---

## 7. One-time environment setup checklist

- [ ] **Python 3.11** installed and visible as `py -3.11`
- [ ] **Node ≥ 18** (`node -v`) — have v24
- [ ] **Docker Desktop** installed **and daemon running** (`docker ps` succeeds)
- [ ] **Foundry** (`anvil --version`, `forge --version`) — for the fork sim + contract
- [ ] repo is a git repo (`git status` succeeds) with a sensible `.gitignore`
- [ ] `.env` created from `.env.example` (gitignored; never committed — rule S3)
- [ ] keys obtained and pasted into `.env` when first needed:
      - `GRAPH_API_KEY` — thegraph.com/studio (free) → PCS v3 subgraph
      - `BSCSCAN_API_KEY` — bscscan.com/myapikey (free) → verified source, contract age
      - `BSC_RPC_URL` — PublicNode works keyless; Nodereal/Ankr for higher limits
- [ ] `pip install` / `npm install` run once, resolved versions written to
      `architecture.md` §Versions (rule R4)
