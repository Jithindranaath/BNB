# Demo video brief — hand this whole file to your recording/voiceover agent

Everything below was verified live against the deployed site on 2026-09-09.
Data is now **frozen** (background jobs stopped) so these numbers will not
drift mid-recording. Do not invent, round up, or "improve" any number below —
narrate exactly what's stated here or exactly what's on screen.

---

## 1. Live URLs

- **Frontend (record this):** https://proofstand.vercel.app
- **Backend API (for reference only, don't show on camera):** https://proofstand-orchestrator.onrender.com
- Confirmed live at recording time: `GET /healthz` → `{"status":"ok","deps":{"db":"ok","rpc":"ok (block 120916814)"}}`

⚠️ **Render free tier sleeps after ~15 min idle** — first request after a sleep
takes up to ~50 seconds to wake up. **Before you start recording**, open
`https://proofstand-orchestrator.onrender.com/healthz` once in a tab and
confirm it returns instantly. If it's slow, wait for that to finish, then
start the actual take — don't record the cold-start wait.

---

## 2. Verified current stats (use these exact numbers, nothing else)

| Agent | Category | n (real runs) | Metric | Window |
|---|---|---|---|---|
| `bnb-grid` | Grid trading | 3 | net_pnl_usd | 6.96 days |
| `pcs-rebalancer` | Rebalancing | 6 | net_fees_usd | 3.13 days |
| `venus-guard` | Health factor | 9 | usd_saved | 365 days (backtest) |
| `pcs-yield` | Yield | 9 | net_apr_delta_pct | — |
| `bsc-sentry` | Security | 11 | wall_seconds | — |

All 38 receipts across all 5 agents are anchored (batched + Merkle-proofed) —
every `/receipt/{id}` page will show a green "verified" checkmark, not a dash.

### Flagship number #1 — bsc-sentry (recommended opener)
Receipt `38d51918-a513-4b6c-8ec9-ffe220f81bb3` — CAKE token audit:
- Agent: **4.57 seconds**
- Human baseline (a real person, stopwatch-timed on BscScan): **54 seconds**
- **Advantage: -49.4s, favorable** — say "12x faster than a manual review"

### Flagship number #2 — venus-guard (recommended second beat)
Receipt `b4d9e2e6-d208-4cc9-b6ef-6eabd98d9554`:
- Baseline (`no_action`, doing nothing): **-$150.01** (a real loss under a real historical ETH drawdown)
- Agent (with guard top-ups): **+$149.89**
- **Advantage: +$299.90, favorable** — say "turns a $150 loss into a $150 gain, a swing of roughly $300"

⚠️ Do **not** say "$156" — that was an older number from an earlier data pull.
The current live number is **$299.90 / ~$300**, not $156.

### Known caveat — do not lead with pcs-yield's number
`pcs-yield`'s current live advantage is **exactly 0** (delta=0.0, "unfavorable").
This is real and explained: the pool with the highest headline APR right now
happens to also be the pool with the best true net APR, so the naive baseline
ties the smart agent. It's honest, not a bug — but it's a boring number on
camera. **Show pcs-yield's page/category tile for diversity credit, but don't
click Hire on it live and don't narrate its delta as if it's impressive.**

`bnb-grid`'s latest receipt is **unfavorable** (-$366 delta) — also real, also
fine to show if asked "does it always win?" (answer: no, and that's the
point — it's measured, not guaranteed).

---

## 3. Recording workflow

### Setup (before hitting record)
1. Open a **fresh incognito/private browser window** — no extensions, no
   bookmarks bar, no dev tools visible.
2. Set the window to a clean resolution (1920x1080 recommended), zoom at 100%.
3. Pre-warm the backend: open `https://proofstand-orchestrator.onrender.com/healthz`
   in a throwaway tab, confirm instant `"status":"ok"`, then close that tab.
4. Navigate to `https://proofstand.vercel.app` and do one silent dry run of
   the full path below before the real take, so you know the timing.

### Recording — screens to capture, in order

| # | Screen / action | Wait for | Approx. duration |
|---|---|---|---|
| 1 | Land on `/` | page fully rendered (category tiles + live activity visible) | 4-5s |
| 2 | Click **"Try an agent — no wallet needed"** CTA | navigates to `/agent/bsc-sentry?target=0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82` | 2s |
| 3 | Click **Hire** (defaults prefilled) | SSE phases stream in (~5-12s), ends on a real verdict | 5-15s |
| 4 | Click **verify →** on the result | lands on `/receipt/{id}` | 2s |
| 5 | Scroll to the **Merkle verification** box | shows green "✓ verified" | 3-4s |
| 6 | Nav → **Report** (`/report`) | table renders all 5 agents with real n/window | 5s |
| 7 | (Optional second beat) Nav → Health factor category → venus-guard → scroll its receipt feed to show the +$299.90 entry | — | 5-8s |

Total: well under 90 seconds of active screen time.

### After recording
- Do a second silent take if the first hire happens to land on an unfavorable
  or zero result for a different agent you clicked into — real data varies
  run to run, so if you deviate from the bsc-sentry/venus-guard path above,
  check the number before committing to that take.

---

## 4. Voiceover script (word-for-word, matched to the screens above)

> **[Screen 1 — landing]**
> "This is an agent marketplace for BNB Chain, where every agent proves its
> value instead of just claiming it. Every run gets compared against a real
> baseline, and the difference — the advantage — is written as a permanent,
> verifiable receipt."
>
> **[Screen 2-3 — CTA → hire]**
> "No wallet, no funds needed to try this. This agent checks a token's
> contract for security red flags — mint permissions, hidden fees, honeypot
> behavior. Let's hire it against CAKE, PancakeSwap's own token."
>
> *(after the verdict appears)*
> "The agent verdicts this in about 5 seconds. The baseline here isn't a
> formula — it's a real person, stopwatch running, manually auditing the same
> contract on BscScan. That took 54 seconds. The agent is roughly 12 times
> faster, and that's not an estimate — it's a measured, timed comparison."
>
> **[Screen 4-5 — receipt / Merkle]**
> "Every one of these numbers becomes a receipt — and the receipt is
> tamper-evident. This box recomputes the cryptographic proof directly in your
> browser and checks it against the anchored root. You're not trusting our
> dashboard, you're verifying the hash yourself."
>
> **[Screen 6 — report]**
> "This report aggregates every agent's real track record — sample size and
> time window shown for every number, nothing hidden, nothing rounded up.
> Right now that's 38 real receipts across all five agents."
>
> **[Screen 7 — venus-guard, optional]**
> "Here's a different agent watching a real Venus borrowing position. Under
> the worst real historical price drawdown, doing nothing would have lost
> about $150. This agent's top-ups turn that into a $150 gain instead — a
> real swing of about $300, backed by an actual receipt."

---

## 5. If something looks different when you actually record

- If the API is slow/errors on first click: it's the Render cold-start (see
  §1) — wait it out off-camera, don't narrate over it.
- If a number on screen doesn't match what's written here: **trust the
  screen, not this document** — live data can shift between when this brief
  was written and when you record. Read the number off the page.
- If `pcs-yield` or `bnb-grid` come up with an unfavorable/zero result on
  camera unexpectedly: that's expected behavior, not a bug — say "results are
  real and vary, they're not guaranteed to always favor the agent" rather
  than avoiding it awkwardly.
