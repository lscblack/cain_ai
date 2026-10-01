# KAI — Knowledge, Analysis & Intelligence

A **local-first OSINT investigation platform**. KAI collects, indexes,
correlates, visualizes, and searches *publicly available* information inside a
single modular intelligence workspace.

> KAI is a dual-use research tool. It is built for authorized use (threat
> intelligence, authorized security assessments, journalism, due diligence).
> It uses public sources only, preserves provenance (source URL + timestamp)
> on every observation, and never presents an inference as a confirmed
> identity.

## Status

Built phase by phase. See `docs/superpowers/specs/` (designs) and
`docs/superpowers/plans/` (implementation plans).

- **Phase 1 — Foundation:** infra, single-operator auth, core abstractions,
  SSRF validator, dashboard. ← current

## Architecture

- **Backend:** FastAPI + SQLModel/SQLAlchemy 2.1 (async, psycopg v3) over
  PostgreSQL, Redis for jobs/cache.
- **Frontend:** React + TypeScript + Tailwind + Vite (intelligence-dark theme).
- **ML/crawl/providers:** added in later phases behind stable interfaces.

## Running Phase 1 (local dev)

Prerequisites: a local PostgreSQL 17 at `127.0.0.1:5432`, Docker (for Redis),
the conda env `fastapi_setup`, and `pnpm`.

```bash
# 1. Infra: Redis (Postgres is your host instance)
docker compose up -d redis

# 2. Config
cp .env.example .env   # then edit credentials/secret

# 3. Database
createdb kai   # or: psql -U postgres -c 'CREATE DATABASE kai;'

# 4. Backend
conda activate fastapi_setup
cd backend
alembic upgrade head
uvicorn app.main:app --reload --app-dir .

# 5. Frontend (new terminal)
cd frontend
cp .env.example .env   # VITE_API_URL only
pnpm install
pnpm dev
```

Open http://127.0.0.1:5173 → on first run, create the operator account → log
in → the dashboard shows a live system-readiness indicator.

### Tests

```bash
conda activate fastapi_setup
cd backend
pytest
```

Backend tests use a disposable `kai_test` database and an in-memory
`fakeredis`, so no running Redis is required for the suite.

## Security guardrails (always on)

- Public sources only; provenance preserved on every observation.
- SSRF protection on every operator-supplied URL.
- Secrets never reach the frontend bundle and are never committed.
- No authentication bypass, brute forcing, or access-control circumvention.
