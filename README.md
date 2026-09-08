# proofstand

An agent marketplace for BNB Chain where every agent carries a verifiable
**receipt trail** — an immutable record of `{agent_run, baseline_run, advantage_delta}`
proving it beats doing the job yourself.

> **Read the docs in this order, every session:**
> [`context.md`](context.md) → [`architecture.md`](architecture.md) →
> the relevant part of [`spec.md`](spec.md) → the current task in [`plan.md`](plan.md).
> [`WORKFLOW.md`](WORKFLOW.md) is the process: the session loop, the phase gates,
> and the session journal.

## Quick start

```bash
# 1. secrets
cp infra/.env.example .env          # then fill keys as tasks need them

# 2. infra (postgres+timescale, redis, anvil)
docker compose up -d
docker compose ps                   # all three healthy

# 3. python (3.11 only — see architecture.md §Versions)
py -3.11 -m venv .venv
.venv/Scripts/activate              # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest

# 4. web
cd apps/web && npm install && npm run dev     # http://localhost:3000

# 5. orchestrator
uvicorn orchestrator.main:app --reload --port 8088 --app-dir services
# port 8088 — the web app's NEXT_PUBLIC_ORCHESTRATOR_URL defaults to :8088

# 6. contracts
cd contracts && forge test

# 7. reference-data verification (rule R1) — expected to FAIL until T-002
cd scripts && npm install && npm run verify:reference
```

## Layout

See [`architecture.md`](architecture.md) §2. In short:
`apps/web` (Next.js) → `services/orchestrator` (FastAPI, receipt layer) →
`services/agents` (5 agents, one interface) → `packages/data` (shared ingestion) →
BNB Chain + Anvil fork. `contracts/` holds `ReceiptAnchor.sol` only.

## The rules that override everything

Real data or an explicit empty state — never a plausible fake (R1–R3).
Tier 0/1 agents cannot sign, by construction. Every UI number carries `n` + window.
BSC mainnet only. Full list: [`context.md`](context.md) §5–§6.
