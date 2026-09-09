# Remaining human steps (T-072)

Everything that can be done from a coding agent is done (see `git log` —
`hires.py` GC fix, stale demo docs, deploy gotchas, `scripts/rehire_singleshot.py`).
What's left needs a person, a browser, a phone, or an account only you hold.
Follow in order — later steps depend on earlier ones landing.

---

## 1. A1 · CAKE manual-analyst row — DONE 2026-09-09

Real audit timed at 54s, recorded in `fixtures/manual_baselines.json`, pushed
and live. This also surfaced and fixed a real bug: `BscSentryAgent.observe()`
never wrote `inputs` into `Observation.data`, so the baseline lookup couldn't
resolve any target regardless of the JSON row — fixed alongside it.

## 2. A2 · Seed the bsc-sentry receipt — DONE 2026-09-09

Ran against the live API. Real receipt: agent 4.57s vs the 54s human baseline,
**delta -49.4s, favorable**. All 5/5 agents now have both-ways receipts;
`docs/acceptance.md` #5 moved to PASS.

## 3. A3 · Confirm CORS is pinned — DONE

`CORS_ALLOW_ORIGINS` confirmed set to the live Vercel origin. Step 1 (deploy +
seed) is now fully done.

---

## 4. B · Receipt depth for the demo — a few hours of wall-clock, needs a real terminal

Every card shows `n=1` right now. The curves on `/agent/[id]` and the
`/report` cards need 5–15 points to look real.

Run in a normal terminal on your machine — **not through an agent** (a
background OOM reaper kills long-running processes in agent sessions):

```bash
export DATABASE_URL="<the Render/Neon postgres URL>"

# bnb-grid + pcs-rebalancer — leave running 6+ hours, ideally overnight
python scripts/run_paper_loops.py --interval 600

# venus-guard + pcs-yield have no continuous loop — re-hire a few points each
python scripts/rehire_singleshot.py --count 8
```

`run_paper_loops.py` resumes from `var/*.json` and never resets. This also
satisfies acceptance item T-040 (the ≥6h continuous grid run).

---

## 5. C · Demo rehearsal (T-072) — needs a person + phone + stopwatch

A1 is done, so the sentry CTA now works against the live site. Do this after
B has run so the curves have real points.

1. Three cold browser passes of the 90-second path in `docs/demo.md` — Wi-Fi
   off / cellular, cold tab, no notes. Fill in the rehearsal-log table. Target
   **< 90 s**. Run against the Vercel URL.
2. The phone acceptance check from `docs/deploy.md` §4 (landing renders, CTA →
   real verdict, `/report` + PDF, a receipt's Merkle box, `/healthz` green).
   Record pass/fail in `docs/acceptance.md`.
3. **Demo-day infra:** Render's free tier stalls the whole event loop during a
   heavy hire (`pcs-rebalancer` has pegged it for ~3 min). For judging, either
   bump to the $7 Starter instance, or pre-warm `/healthz` a minute before
   going on stage and stick to venus-guard / warm-cache grid live, and ping
   `/healthz` every 10 min so it never cold-sleeps mid-session.

---

## 6. D · Optional upgrades — only if time allows

### D1 · Envio HyperIndex PCS v3 indexer — ~1–2 h + first sync, needs an Envio account

Follow `docs/envio-indexer.md`: deploy the indexer, wait for the initial sync,
set the `PCS_V3_GRAPHQL_URL` env var. Payoff: `pcs-yield` ranks v3 pools
instead of v2, and the v3 long tail gives the sentry gate a real chance to show
an exclusion (the current v2 blue-chip set never triggers `CRITICAL`, so
that "most memorable" beat currently shows an empty list). Economics don't
change.

### D2 · Tier-2 live + mainnet anchor (T-041 / T-043 / T-062) — needs a funded low-value key

Fresh EOA + a few $ of BNB for gas. Set `SESSION_KEY_PRIVATE_KEY` and/or
`ANCHOR_PRIVATE_KEY` in the Render env (never commit these). Deploy
`ReceiptAnchor.sol` to mainnet, put the address in
`packages/data/reference/addresses.json`, run `scripts/anchor_receipts.py`
against mainnet BSC, and verify on BscScan instead of the local-anvil anchor.

**Risk:** this is the first real-mainnet run of code only proven on an Anvil
fork — dry-run it well before the demo, not during.

---

## Suggested order

- **A1, A2, A3 are all done.** Next: kick off B overnight.
- **Tomorrow:** C (rehearsal + phone check) once B has run.
- **If time allows:** D1, then D2.
