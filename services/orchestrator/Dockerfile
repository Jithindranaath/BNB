# proofstand orchestrator — production image (T-070).
# Build context is the REPO ROOT:  docker build -f services/orchestrator/Dockerfile -t proofstand-orchestrator .
#
# Runtime deps: a Postgres URL in DATABASE_URL (TimescaleDB optional — the
# migration degrades to a plain table when the extension is absent, so any free
# managed Postgres works). Redis is optional; without REDIS_URL the hot cache is
# simply bypassed. No API keys are required for a first deploy (BscScan / The
# Graph keys only unlock the sentry contract-age check and pcs-yield).

FROM python:3.11.9-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---- source (both roots: packages/ shared libs, services/ apps) ----
COPY pyproject.toml README.md ./
COPY packages/ packages/
COPY services/ services/
COPY migrations/ migrations/
COPY alembic.ini ./

# Editable install keeps the reference JSON / manifest.yaml files resolvable in
# place via Path(__file__) — same as local dev.
RUN pip install --upgrade pip && pip install -e .

COPY infra/deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Hosts (Render, Railway, Fly, Koyeb…) inject $PORT; fall back to 8088.
ENV ORCHESTRATOR_PORT=8088
EXPOSE 8088

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve"]
