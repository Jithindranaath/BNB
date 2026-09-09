# Deploy (T-070)

Two halves, both on free tiers:

| Half | Host | What runs |
|---|---|---|
| Front end | **Vercel** (free) | `apps/web` — Next.js 15, static + server components |
| Orchestrator | **Render** (free web service) + **Render Postgres** (free) | FastAPI API, migrations, in-process hire manager |

Redis is **not** deployed — the hot cache in `packages/data/cache.py` bypasses
itself when Redis is absent. The trading agents' paper loop
(`scripts/run_paper_loops.py`) is **not** part of this deploy; it runs from a
real terminal (see `WORKFLOW.md` §5).

`anvil` (Foundry 1.8.1) is baked into the orchestrator image — `bsc-sentry`
forks BSC mainnet on every hire and `pcs-yield`'s security gate does too. The
image is ~1 GB because of it; well within Render's limit.

Acceptance: the site is reachable from a phone on cellular data, cold, with no
VPN, and `/healthz` reports `db` and `rpc` ok.

---

## 0. One-time prep

```bash
# from the repo root
git remote add origin git@github.com:<you>/proofstand.git
git push -u origin master
```

Render and Vercel both deploy from the GitHub repo.

---

## 1. Orchestrator → Render

### 1a. Blueprint (recommended)

`render.yaml` at the repo root defines the web service **and** a free Postgres,
with `DATABASE_URL` auto-wired.

1. [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**
2. Pick the repo. Render reads `render.yaml`.
3. Fill the vars marked `sync: false`:
   - `CORS_ALLOW_ORIGINS` — leave blank for now (set in step 3).
   - `BSCSCAN_API_KEY` — optional; blank is fine (sentry contract-age check
     degrades to "unknown").
   - `GRAPH_API_KEY` — optional; blank keeps `pcs-yield` unavailable (T-033).
4. **Apply**. First build takes ~5 min (Docker image).

The container entrypoint runs `alembic upgrade head` before `uvicorn`, so the
schema is created on first boot. TimescaleDB is absent on Render Postgres — the
migration detects that and creates `runs` as a plain table (composite PK and all
queries are identical).

### 1b. Verify

```bash
curl https://proofstand-orchestrator.onrender.com/healthz
# {"status":"ok","deps":{"db":"ok","redis":"down","rpc":"ok (block NNNNN)", ...}}
```

`redis: down` is expected and does **not** make the status `degraded` — only
`db` and `rpc` count.

Note the service URL — you need it for the front end.

### Free-tier caveats

- **Sleeps after ~15 min idle**; the next request takes ~50 s to wake it. For a
  live demo, hit `/healthz` a minute before you present, or add an external
  uptime pinger (e.g. a free cron-job.org GET every 10 min).
- **Free Postgres is deleted ~30 days after creation.** For anything longer,
  create a free [Neon](https://neon.tech) database and replace `DATABASE_URL`
  in the Render service env (paste Neon's `postgresql://…?sslmode=require`
  URL as-is — the scheme is rewritten automatically). Re-deploy; the entrypoint
  re-runs migrations on the new DB.
- **No persistent disk** — the parquet kline cache rebuilds from Binance on each
  cold start. `read_klines` handles this.

### Alternative hosts

The image is host-agnostic (`docker build -f services/orchestrator/Dockerfile .`).
Railway, Fly.io, and Koyeb all work the same way: point at the Dockerfile, set
`DATABASE_URL`, expose the injected `$PORT`. Fly.io has no idle sleep if the
cold-start wait bothers you.

**Also set `BINANCE_BASE_URL=https://data-api.binance.vision` on any host you
add outside `render.yaml`** (see below) — the blueprint already carries it.

### Two gotchas already fixed — don't rediscover them on a new host

- **Binance geoblocks `api.binance.com` (HTTP 451)** from most datacentre IPs,
  Render's included. `render.yaml` points `BINANCE_BASE_URL` at
  `https://data-api.binance.vision` instead — same `/api/v3/klines` +
  `/api/v3/ticker/price` shape, no auth, not geofenced. If you deploy anywhere
  `render.yaml` doesn't apply (a manual Railway/Fly/Koyeb service, or a fresh
  Render service built by hand instead of the Blueprint), set this env var
  yourself or every kline pull 451s.
- **Runtime fixtures ship in the image.** `gas_units.json` and
  `manual_baselines.json` are read at runtime (`packages/data/cache.py`,
  `services/orchestrator/baselines.py`) via a path resolved from
  `Path(__file__)`, not bundled into the wheel — the Dockerfile has an explicit
  `COPY fixtures/ fixtures/` for this. If a future refactor moves the
  Dockerfile or changes the build context, keep that line or `bsc-sentry`'s
  baseline (and gas-cost figures) silently 404 in prod only.

---

## 2. Front end → Vercel

### 2a. Import

1. [vercel.com/new](https://vercel.com/new) → import the repo.
2. **Root Directory: `apps/web`** (critical — the repo is a monorepo).
   Framework preset **Next.js** is auto-detected; `apps/web/vercel.json` pins it.
3. **Environment Variables** →
   `NEXT_PUBLIC_ORCHESTRATOR_URL = https://proofstand-orchestrator.onrender.com`
   (the Render URL from step 1b, **no trailing slash**). This is read at
   **build time** (`apps/web/lib/api.ts`), so it must be set before the build.
4. Deploy.

### 2b. CLI alternative

```bash
cd apps/web
npx vercel --prod \
  -e NEXT_PUBLIC_ORCHESTRATOR_URL=https://proofstand-orchestrator.onrender.com
```

---

## 3. Wire CORS back

Once you have the Vercel URL (e.g. `https://proofstand.vercel.app`):

1. Render → the service → **Environment** →
   `CORS_ALLOW_ORIGINS = https://proofstand.vercel.app`
   (add your custom domain too, comma-separated, if you have one).
2. Save → Render redeploys.

Until this is set the API allows `*`, so the site works either way — but pin it.

---

## 4. Acceptance check (do this on a phone, on cellular, Wi-Fi off)

1. Open `https://<vercel-url>` cold. Landing renders: 5 category tiles, live
   ticker, "Try an agent — no wallet needed" CTA.
2. Follow the CTA → `bsc-sentry` with the CAKE address prefilled → **Run** →
   a real verdict with evidence, no wallet.
3. `/report` → the Agent Advantage Report table renders with real `n` and
   window lengths; **Download PDF** returns a PDF.
4. Open any receipt → the Merkle section shows the leaf; if a batch has been
   anchored, the browser verifier recomputes the root.
5. `https://<render-url>/healthz` → `db` and `rpc` ok.

Record pass/fail per `spec.md` §11 in `docs/acceptance.md` (T-071).

---

## 5. Rollback

- **Front end**: Vercel → Deployments → previous → **Promote to Production**.
- **Orchestrator**: Render → the service → **Manual Deploy** → **Rollback** to
  the previous image. The schema is forward-only; a rollback of code is safe
  because migration `0001` is the only one.

---

## 6. What is NOT deployed here

- The Tier-2 live trading loop and the BSC-mainnet receipt anchor — both gated
  on funded keys (`SESSION_KEY_PRIVATE_KEY`, `ANCHOR_PRIVATE_KEY`). Proven on
  Anvil forks; see `plan.md` T-041 / T-043 / T-062.
- Redis, Hummingbot, Gateway (the `trading` compose profile).
- `pcs-yield` — needs a working The Graph query key (T-033).
