# Demo script + rehearsal (T-072)

The 90-second cold path a judge walks, the exact clicks, what to say, and the
measured backend latency of every beat. Plus the two beats that need an external
input before the live demo, with the fix for each.

Prereqs: `docker compose up` healthy, orchestrator on :8088, web on :3000,
receipts seeded (`scripts/run_paper_loops.py` has run at least a few cycles),
and a batch anchored (see **Pre-demo checklist**).

---

## The path (target: 90 s)

| # | Beat | Click | Say | Backend time* |
|---|---|---|---|---|
| 0 | **Land** | open `/` | "An agent marketplace on BNB Chain. Every run writes a receipt: agent value, baseline value, advantage delta — you verify the hash, not the dashboard." | `/agents`+`/categories`+`/activity` ≈ **90 ms** total |
| 1 | **Pick the dramatic agent** | category tile **Health factor** → **Venus health-factor guard** | "This one watches a Venus borrow position and tops it up before liquidation." | `/agents/venus-guard` ≈ **40 ms** |
| 2 | **Hire, no wallet** | **Hire** → defaults are prefilled → **Run** | "Tier 1 — paper on live prices, no funds at risk. It's replaying a real 365-day ETH drawdown against a real on-chain borrower." | SSE run **≈ 12 s** (365 d of klines + on-chain reads) |
| 3 | **The receipt** | the run view shows the result → **verify →** | "Under the worst real drawdown this account gets liquidated for \$156. The guard's top-ups prevent it — it saves \$156. That number is now a receipt." | `/receipts/{id}` ≈ **30 ms** |
| 4 | **Verify the hash** | on `/receipt/{id}`, the **Merkle verification** box | "The page recomputes the Merkle root from the leaf and proof in your browser with @noble/hashes, and checks it against the anchored root. Green = the number wasn't touched." | client-side, instant |
| 5 | **The report** | nav → **Report** | "Every both-ways task, generated from the receipts table — n, window, methodology, backtests labelled. `Download PDF` for the judges." | `/report/advantage` ≈ **45 ms**, `.pdf` ≈ **0.5 s** |

\* measured 2026-09-07 against the local stack, reads < 50 ms each. The wall-clock
budget is dominated by beat 2's live run (~12 s) and by the human talking.

### If you want a faster beat 2

Use **bnb-grid** (Grid trading tile) instead of venus-guard — a Tier-1 grid hire
completes end to end in **~2 s**. Trade-off: the grid's delta vs hodl swings
either way on the current window (it is a real result, not a scripted win),
whereas venus-guard's "-\$156 → saved \$156" lands every time. For the demo,
venus-guard is the stronger story; grid is the safer clock.

---

## Pre-demo checklist

```bash
# 1. infra
docker compose up -d           # postgres, redis, anvil — wait for healthy

# 2. receipts (need >= a few per agent for the curves + report)
python scripts/run_paper_loops.py --interval 600     # leave running in a real terminal

# 3. anchor a batch so /receipt pages show a real proof + tx
#    (create_batch groups every unbatched receipt; submit_batch anchors it)
python scripts/anchor_receipts.py                     # local anvil :8545

# 4. services
python -m uvicorn orchestrator.main:app --app-dir services --port 8088
cd apps/web && npm run dev                            # :3000

# 5. smoke
curl -s localhost:8088/healthz         # status: ok  (db + rpc ok)
open http://localhost:3000
```

Then dry-run the path above once before going live.

---

## Rehearsal log

### Programmatic rehearsal — 2026-09-07 (this session)

Every beat's backend call was driven directly and checked:

```
/agents            200  0.051s
/categories         200  0.019s
/activity           200  0.019s
/agents/venus-guard 200  0.038s
/receipts/{id}      200  0.028s   anchored_tx set, root set, proof = 4 nodes
/report/advantage   200  0.047s
/report/advantage.pdf 200 0.495s
grid Tier-1 hire end-to-end: 2.1s   (venus-guard hire: ~12s)
```

All green. Sum of non-run latency ≈ 0.7 s; the human narration and beat-2 run
set the real pace.

### Cold browser rehearsals — TO DO (needs a person + stopwatch)

Run three times, Wi-Fi off / cellular, cold tab, no notes. Record:

| run | land→result | result→verified | total | notes |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

Target total < 90 s. If beat 2 dominates, switch to bnb-grid.

---

## Beats NOT in this cut — fix before the live demo

### A. The `bsc-sentry` beat (the landing CTA points here)

`spec.md` §9.2 mandates the primary CTA deep-link to
`/agent/bsc-sentry?target=0x0E09…CE82` (CAKE). The sentry **verdict engine works
on real BSC** (`tests/test_sentry.py` live, 2 pass) — but a *hire* through the
marketplace runs the both-ways harness, and `bsc-sentry`'s baseline is
`manual_analyst`, read from `fixtures/manual_baselines.json`, which holds only
the sample row. So the hire fails at the baseline step and the run view shows an
error, not the verdict.

**Fix (≈ 2 min, needs a human):** a teammate audits CAKE by hand with BscScan,
stopwatch running, and adds a real row to `fixtures/manual_baselines.json` keyed
by the lowercased address. The findings are already gathered in
`docs/findings/T-072-cake-audit.md` — a human just needs to confirm them and
record their own wall-clock time (the number must be *measured*, not estimated —
`fixtures/manual_baselines.json` header rule).

**Until then:** after landing, go to **venus-guard** (or grid) instead of
following the sentry CTA. Do not click the CTA on stage.

### B. The `pcs-yield` × `bsc-sentry` composition ("yield refuses a flagged pool")

`spec.md` §4.2 / `context.md` §"most memorable" — the yield router excludes any
pool `bsc-sentry` flags `CRITICAL`, shown in a visible "excluded by security
agent" section. **`pcs-yield` has no implementation** (only a manifest —
`services/agents/pcs_yield/` has no `agent.py`). It is T-033, held for a working
The Graph query key.

As of T-072 the marketplace shows this honestly: the **Yield** category tile
still renders (main-track diversity), the `pcs-yield` card renders with a
**"Not yet available — needs a The Graph query key (T-033)"** badge, the agent
page hides the Hire panel, and `POST /hires` for it returns **409** with that
reason (instead of failing deep in a worker thread).

**Fix:** land a working Graph key → build `pcs_yield/agent.py` (the subgraph
client `packages/data/sources/subgraph.py` is already complete and parked) →
wire the sentry gate. Tracked as T-033.

---

## One-liners to have ready

- "The receipt is `{agent_run, baseline_run, advantage_delta}` — same primitive
  for every agent, security to trading."
- "Baselines are real: hodl is marked to market, `no_action` replays the actual
  liquidation, the analyst baseline is a human with a stopwatch. Nothing is
  estimated."
- "Backtests are labelled `BACKTEST` with the replay method — never blended into
  a live number."
- "Anchored on-chain; the proof verifies in your browser. Right now that's a
  local chain — mainnet anchoring just needs a funded low-value key."
