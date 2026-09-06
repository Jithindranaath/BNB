# context.md

> **Read this file first, before every work session.**
> It defines what we are building, why, and the rules you must never break.
> If anything in another doc contradicts this file, this file wins.

---

## 1. Project

**Codename:** `proofstand`
**One line:** An agent marketplace for BNB Chain where every agent carries a verifiable receipt trail proving it beats doing the job yourself.

Rename the product freely, but change it in exactly one place: `apps/web/config/brand.ts`. Never hardcode the name anywhere else.

## 2. Why this exists

We are entering a hackathon with three overlapping rubrics. They share one weak point that most teams will fail: **nobody measures anything.**

| Rubric | Criterion | Weight |
|---|---|---|
| TermiX | Value of services (they will hire from our marketplace and evaluate) | 30% |
| TermiX | Proven agent advantage — *measured, not asserted* | 30% |
| TermiX | High-stakes categories + track record (trading/security weighted higher) | 20% |
| TermiX | Marketplace quality — find, compare, hire without instructions | 20% |
| Main track | Functionality — full journey works end to end | ~33% |
| Main track | Data quality — real-time, beyond basic counts | ~33% |
| Main track | Agent diversity — all four categories, equal depth | ~33% |
| PancakeSwap | Real benefit to PCS traders/LPs, funds never at risk | pass/fail |

**The strategic insight driving every design decision:** a receipt layer that records `{agent_run, baseline_run}` for every job satisfies TermiX "proven advantage" (30%), TermiX "track record" (20%), and main-track "data quality" (33%) with one primitive. Build it once, get scored three times.

## 3. The three things that decide whether we win

1. **A judge must get real value with no wallet and no funds, in under 2 minutes.** TermiX will land cold and hire something. If they hit a "connect wallet / deposit / wait 6 hours" wall, we score zero on the 30% value criterion regardless of code quality. This is why Tier 0 agents exist and why they ship first.
2. **Every number on screen must be measured, with sample size and window shown.** `n=14 runs, 6-day window` beats a clean unlabeled equity curve. Judges in a trading track discount everything if one number smells fabricated.
3. **All four categories, equal depth.** Depth = own data sources, own baseline definition, own receipts. Not four cards pointing at one engine.

## 4. Non-goals — do not build these

- ML models, model training, backtesting frameworks beyond the baseline runner
- Custody of user funds under any circumstance
- Token, tokenomics, points, or airdrop mechanics
- Mobile app, i18n, dark/light theme switcher beyond Tailwind defaults
- Multi-chain. **BSC mainnet only.** Testnet only for contract dry runs.
- User accounts with passwords. Wallet connect or anonymous session, nothing else.
- Any agent that autonomously decides trade *direction* from an LLM output

## 5. Anti-hallucination rules — MANDATORY

These exist because a fabricated contract address or API endpoint destroys the project silently.

**R1. Never invent an address, endpoint, ABI, or subgraph ID.**
All of them live in exactly one place: `packages/data/reference/`. Every entry carries `"verified": false` until a human confirms it against the official source cited in the same record. `scripts/verify_reference.ts` must pass before any agent touches mainnet. If you need an address that is not in that file, **stop and ask** — do not guess, do not recall from memory.

**R2. Never invent a number.**
No placeholder APRs, no example win rates, no `// TODO: replace with real data` values that render in the UI. If data is unavailable, the UI shows an explicit empty state (`"No runs yet"`), never a plausible-looking fake. Seed/demo data, if used at all, lives in `fixtures/` and is visually badged `DEMO` in the UI.

**R3. Never synthesize market data.**
No GBM price generators, no random walks, no "representative" OHLCV. Real data or no data. Reason: synthetic prices have no volatility clustering or fat tails, so every strategy calibrated on them is calibrated on fiction — and a judge who spots it discounts the entire submission.

**R4. Pin versions on first install and record them.**
When you run the first `npm install` / `pip install`, write the resolved versions into `architecture.md` §Versions. Do not assume a version from memory.

**R5. When an API's shape is unknown, probe it before coding against it.**
Write a one-off script under `scripts/probe/`, print the actual response, then write the typed client. Never write a parser for a response you have not seen.

**R6. Uncertainty is reported, not smoothed over.**
If you are unsure whether something works (e.g. whether Hummingbot Gateway supports PancakeSwap writes), say so explicitly in your output and mark the code path `UNVERIFIED`. Do not write code that assumes it works and hope.

**R7. One source of truth per fact.**
Constants, addresses, thresholds, and copy each live in exactly one module. If you find yourself writing a value that already exists elsewhere, import it.

## 6. Safety rules — MANDATORY

**S1.** The LLM never signs, never picks trade direction, never chooses an amount. It parses intent into a validated config and writes prose. All decisions are deterministic code.
**S2.** Live execution uses a session key scoped to: one router address, one pool, a spend cap, and an expiry. Revocable in one click. The permission diff is shown to the user before signing.
**S3.** No private key ever enters the database, logs, or an LLM prompt. Runtime keys live in env vars, loaded once.
**S4.** Every agent has a hard kill switch and a max-loss circuit breaker that halts and reports rather than retrying.
**S5.** Tier 0 and Tier 1 agents must be provably incapable of signing a transaction — enforce by construction (no signer in scope), not by convention.

## 7. Glossary — use these words exactly

| Term | Meaning |
|---|---|
| **Agent** | A deterministic policy engine with a manifest, hireable from the marketplace |
| **Run** | One execution of an agent against one task |
| **Baseline** | The counterfactual run: what happens if the user does nothing, or does it manually |
| **Receipt** | The immutable record of a run + its baseline + the advantage delta |
| **Advantage** | `agent_value − baseline_value` on a named metric, with units |
| **Tier 0 / 1 / 2** | No-wallet read-only / paper trading / live non-custodial |
| **Calibration** | Computing strategy parameters from recent real data. **Not** training. |
| **Manifest** | The YAML describing an agent; the only thing the marketplace renders from |

Never write "training", "model", or "prediction" about our agents. They are calibrated policy engines. This distinction is a talking point, not a technicality.

## 8. The five agents

| ID | Category | Tier | Why it exists |
|---|---|---|---|
| `pcs-rebalancer` | Rebalancing | 1, 2 | Main-track mandated + PancakeSwap challenge |
| `bnb-grid` | Grid trading | 1, 2 | Main-track mandated + TermiX trading track record |
| `pcs-yield` | Yield optimisation | 0 | Main-track mandated + Tier 0 judge entry point |
| `venus-guard` | Health factor | 1, 2 | Main-track mandated |
| `bsc-sentry` | Security | 0 | TermiX weights security above general-purpose; Tier 0 |

`bsc-sentry` gates `pcs-yield`: the yield agent refuses to route into a pool sentry flags. Build this composition — it is the most memorable thing in the demo.

## 9. How the coding agent should work

- Read `context.md` → `architecture.md` → the relevant section of `spec.md` → the current task in `plan.md`. In that order, every session.
- Work one `plan.md` task at a time. Do not start a task whose dependencies are unmet.
- Every task has acceptance criteria. Run them. Report pass/fail honestly. A failing test reported is worth more than a passing test faked.
- Commit per task, message format: `[T-<id>] <what changed>`.
- When you finish a task, update its status in `plan.md` and stop for review.
- If a task takes more than ~90 minutes of tool calls, stop and report the blocker instead of thrashing.
