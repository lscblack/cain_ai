# KAI — Phase 1: Foundation (Design Spec)

**Date:** 2026-10-01
**Status:** Approved for implementation planning
**Author:** lscblack (tech@nexventures.net) with Claude Code

---

## 1. Purpose & Context

KAI (**K**nowledge, **A**nalysis & **I**ntelligence) is a local-first OSINT
investigation platform. This spec covers **Phase 1 only**: the runnable
foundation that every later module bolts onto.

**Operating context (decided):** solo operator, local machine, single user.
No multi-tenancy, no roles, no open registration.

**Outcome of Phase 1:** a developer can bring up infrastructure, run the
backend (host conda env) and frontend (pnpm/Vite), register the single
operator on first run, log in, and see an authenticated dashboard whose
"system online" indicator reflects a live backend readiness check against
Postgres and Redis. **No OSINT features exist yet** — this is the skeleton
and the core abstractions.

**Why it matters:** the seams defined here — config, DB session, auth
dependency, and the stub abstractions (`BaseProvider`,
`Entity`/`Evidence`/`Relationship`, repository pattern) — are what let
Phases 2–18 be added without rewriting the core. The project's stated goal
is "a serious modular intelligence platform, not a collection of scripts."

### Non-negotiable guardrails (acceptance criteria, every phase)

KAI is a dual-use tool. These are requirements, not polish:

- Public sources only; preserve **source URL + collection timestamp** on
  every observation (enforced structurally once evidence lands in Phase 2+).
- Never present inference as confirmed identity. UI language: "potential
  match", "observed on source" — never "this is definitely X".
- **SSRF protection** on any operator-supplied URL (shipped in Phase 1,
  before any crawler exists, so no later phase can forget it).
- Secrets never reach the frontend; secrets never committed to git.
- No auth bypass, no brute force, no access-control circumvention.

---

## 2. Scope

### In scope (Phase 1)

- Monorepo skeleton (backend / frontend / infra / docs).
- `docker-compose.yml` bringing up **Redis** and (optionally) a
  pgvector-enabled Postgres; host Postgres is the default DB.
- FastAPI app: config, logging, DB session, health endpoints, auth.
- Single-operator auth: first-run register (locks after first user),
  login, `/auth/me`, JWT bearer, argon2 password hashing.
- `users` and `audit_logs` tables; Alembic migrations.
- **Stub abstractions** (code interfaces, no tables yet): `BaseProvider`
  ABC; abstract `Entity`/`Evidence`/`Relationship` base models; generic
  repository base.
- SSRF-safe URL validator utility + unit tests.
- React/TS/Tailwind frontend: intelligence-dark theme tokens, auth
  context, Login page, Dashboard page with live readiness indicator.
- Tests (TDD) for all backend logic above.
- `.env.example` (placeholders only), `.gitignore`, `README.md`.

### Explicitly out of scope (later phases)

Cases/investigations (Phase 2), universal search (3), phone/email/username
intelligence (4–6), evidence graph (7), face detection/embeddings/index
(8–9), crawler (10), reverse-image discovery (11), live face UI (12), maps
(13), power-up providers (14), AI analyst (15), timeline/graph viz (16),
perf (17), security hardening pass (18). Face ML libs, Playwright, Scrapy,
Celery, Qdrant/Milvus, MinIO are **not** installed in Phase 1.

---

## 3. Architecture

### 3.1 Repository layout (Phase 1 creates only these)

```
cain_ai/
  backend/
    app/
      main.py                  # app factory, CORS, router mount, startup/shutdown
      core/
        config.py              # pydantic-settings; reads .env
        security.py            # argon2 hashing, JWT encode/decode
        logging.py             # structured logging config
        net.py                 # SSRF-safe URL validator
      database/
        session.py             # async engine + get_session dependency
        base.py                # SQLModel mixins: UUID id, created_at/updated_at
        models/
          user.py              # User table
          audit.py             # AuditLog table
        entities.py            # ABSTRACT Entity / Evidence / Relationship (no tables)
        repositories/
          base.py              # generic async repository
          user_repo.py
          audit_repo.py
      api/
        deps.py                # get_current_operator, get_db
        auth.py                # /auth/register, /auth/login, /auth/me
        health.py              # /health, /health/ready
      providers/
        base.py                # BaseProvider ABC (stub)
      __init__.py
    tests/
      conftest.py              # test db + fakeredis fixtures, async client
      test_security.py
      test_net_ssrf.py
      test_auth.py
      test_health.py
    alembic/                   # env.py, versions/
    alembic.ini
    pyproject.toml             # metadata only; env is conda `fastapi_setup`
  frontend/
    src/
      main.tsx  App.tsx
      lib/api.ts               # fetch wrapper + token storage
      lib/auth.tsx             # AuthProvider + useAuth
      components/
        AppShell.tsx
        StatusIndicator.tsx
      pages/
        Login.tsx
        Dashboard.tsx
      styles/theme.css         # CSS custom properties (design tokens)
    index.html
    vite.config.ts
    tailwind.config.ts
    postcss.config.js
    tsconfig.json
    package.json               # pnpm
  infra/
    docker/
      backend.Dockerfile       # for later full containerization (not dev loop)
  docker-compose.yml           # redis + optional pgvector postgres
  .env.example
  .gitignore
  README.md
  docs/superpowers/specs/
```

### 3.2 Runtime & tooling

- **Backend dev:** host conda env `fastapi_setup` (Python 3.11.13). All
  deps already present: fastapi, uvicorn, sqlmodel, SQLAlchemy 2.1,
  alembic, psycopg (v3), asyncpg, redis+hiredis, fakeredis, argon2-cffi,
  python-jose, pytest, pytest-asyncio, httpx. **No installs needed.**
- **DB driver:** `postgresql+psycopg` (psycopg v3) for both the async app
  engine and Alembic — one driver, matches the operator-provided URL.
- **DB default:** host Postgres 17.7 at `127.0.0.1:5432`, database `kai`.
- **Frontend:** pnpm + Vite + React + TypeScript + Tailwind; Framer Motion
  and lucide-react installed, minimally used in Phase 1.
- **Infra via docker-compose:** Redis (required). A `pgvector/pgvector`
  Postgres service is provided but commented/optional, since the default is
  the host Postgres.

### 3.3 Configuration (`core/config.py`, pydantic-settings)

Settings read from `.env`. Keys (values only in gitignored `.env`):

```
APP_ENV=dev
APP_SECRET_KEY=            # JWT signing secret
ACCESS_TOKEN_EXPIRE_MINUTES=720
DATABASE_URL=postgresql+psycopg://postgres:***@127.0.0.1:5432/kai
REDIS_URL=redis://127.0.0.1:6379/0
CORS_ORIGINS=http://127.0.0.1:5173
```

Frontend env is separate and contains **only** `VITE_API_URL` — never a
secret. `.env.example` ships placeholders only.

---

## 4. Component Design

### 4.1 Auth (single-operator)

- **Password hashing:** `argon2-cffi` `PasswordHasher` wrapped in
  `security.hash_password` / `verify_password`.
- **JWT:** `python-jose`, HS256, signed with `APP_SECRET_KEY`. Payload:
  `sub` (user id), `exp`. Access token only (no refresh rotation — solo
  local); expiry configurable, default 12h.
- **Endpoints:**
  - `POST /auth/register` — body `{email, password}`. **Succeeds only
    while `users` is empty**; otherwise `403 registration_closed`. Creates
    the operator, writes an audit entry.
  - `POST /auth/login` — body `{email, password}`; returns
    `{access_token, token_type}`. Failures are constant-time-ish (always
    run a hash verify) and audited.
  - `GET /auth/me` — requires valid bearer token; returns operator profile.
- **Dependency:** `deps.get_current_operator` decodes the token, loads the
  user, 401 on any failure.

### 4.2 Health

- `GET /health` — public liveness, `{"status":"ok"}`.
- `GET /health/ready` — checks Postgres (`SELECT 1`) and Redis (`PING`);
  returns per-dependency status and an overall boolean. Drives the
  dashboard "SYSTEM ONLINE ●" indicator.

### 4.3 Audit log

`AuditLog` table: `id`, `created_at`, `actor_id` (nullable), `action`
(e.g. `operator.register`, `operator.login`, `operator.login_failed`),
`detail` (JSON), `ip`. Written on auth events in Phase 1; reused platform-
wide later. `audit_repo.record(...)` helper.

### 4.4 SSRF validator (`core/net.py`)

`validate_public_url(url) -> ParsedUrl | raises UnsafeUrlError`. Rejects:
non-http(s) schemes; hostnames resolving to loopback, private RFC1918,
link-local `169.254.0.0/16` (incl. `169.254.169.254`), unique-local IPv6
`fc00::/7`, `::1`, `0.0.0.0`; and bare `localhost`. Resolves DNS and checks
**every** returned A/AAAA record (DNS-rebinding-aware). Pure, synchronous,
fully unit-tested with an allow/block table. Not wired to any caller in
Phase 1 — it exists so Phase 10's crawler must use it.

### 4.5 Stub abstractions (interfaces only, no DB tables)

- `providers/base.py` — `BaseProvider` ABC:
  `name: str`, `type: str`, `enabled: bool`, and async methods
  `health_check()`, `search(query)`, `enrich(entity)`, plus
  `rate_limit()` / `configuration()`. Raises `NotImplementedError`.
- `database/entities.py` — abstract SQLModel-free base classes /
  Pydantic models describing the shape of `Entity`, `Evidence`,
  `Relationship` (fields: ids, type, source_url, collected_at, first_seen,
  last_seen, hash, confidence, raw/processed metadata). Documented as the
  contract Phase 2+ will realize as concrete tables. No migrations emitted.

### 4.6 Database session (`database/session.py`)

Async engine from `DATABASE_URL`; `async_sessionmaker`; `get_session`
FastAPI dependency yielding a session with commit/rollback handling.

### 4.7 Frontend

- **Theme tokens** (`styles/theme.css`, CSS custom properties): near-black
  bg `#0a0b0d`, navy panels `#111622`, red accent `#e5484d` (sparingly),
  verified-green `#30a46c`, warning-amber `#f5a623`, text white/gray, mono
  font for metadata, thin borders, minimal glow. No gradients/heavy
  shadows. Tailwind config maps these tokens to utilities.
- **`lib/api.ts`:** `fetch` wrapper; base `VITE_API_URL`; attaches bearer
  token from storage; parses errors into a typed shape.
- **`lib/auth.tsx`:** `AuthProvider` + `useAuth` (token in `localStorage`,
  `login`, `logout`, `me` on mount, loading state).
- **Pages:** `Login` (email/password → `/auth/login`); `Dashboard`
  (protected; shows operator email, a `StatusIndicator` polling
  `/health/ready`, and placeholder stat tiles matching the spec's dashboard
  mock — Faces/Phones/Emails/Sources all `0`/`—` for now). First-run
  experience: if `/auth/me` 401s and registration is open, Login offers a
  "create operator" affordance hitting `/auth/register`.

---

## 5. Data Model (Phase 1 tables only)

```
users
  id            uuid pk
  email         text unique not null
  password_hash text not null
  created_at    timestamptz
  updated_at    timestamptz

audit_logs
  id         uuid pk
  created_at timestamptz
  actor_id   uuid null  (fk users.id)
  action     text not null
  detail     jsonb null
  ip         text null
```

Managed by **Alembic**. No schema changes outside migrations.

---

## 6. Testing (TDD)

Written before implementation, run in conda `fastapi_setup`:

- `test_security.py` — argon2 hash round-trip + wrong-password reject; JWT
  encode/decode; expired token rejected.
- `test_net_ssrf.py` — allow/block table: public host allowed; loopback,
  10.x/192.168.x/172.16.x, 169.254.169.254, `localhost`, `::1`, `file://`
  all blocked; multi-record DNS where any private record blocks.
- `test_auth.py` — register succeeds when empty; second register 403;
  login success returns token; wrong password 401; `/auth/me` without token
  401, with token 200; audit rows written.
- `test_health.py` — `/health` 200; `/health/ready` reports db+redis
  (Postgres via test db, Redis via **fakeredis**, so no live Redis needed).

Test infra: `conftest.py` provides an isolated test database
(transaction-rollback or a disposable `kai_test` db) and a fakeredis-backed
client, plus an httpx `AsyncClient` against the ASGI app.

---

## 7. Deployment / Dev Workflow

1. `docker compose up -d redis` (Postgres is the host instance).
2. Create db: `createdb kai` (or via psql) — captured in README + a
   `scripts/` helper.
3. Backend: `conda activate fastapi_setup`; `alembic upgrade head`;
   `uvicorn app.main:app --reload`.
4. Frontend: `pnpm install`; `pnpm dev` (Vite on 5173).
5. Open frontend → register operator (first run) → log in → Dashboard
   shows green readiness.

**pgvector note:** not required until Phase 8. Before Phase 8, enable it on
the host Postgres (`sudo apt install postgresql-17-pgvector` then
`CREATE EXTENSION vector;`) **or** migrate KAI's DB to the
`pgvector/pgvector:pg17` compose service. Tracked as a Phase 8 prerequisite.

---

## 8. Definition of Done

- `docker compose up -d redis` + host Postgres + `alembic upgrade head`
  succeed.
- Backend serves `/health`, `/health/ready`, and the three auth endpoints
  with the documented behavior.
- Frontend: register (first run) → login → protected Dashboard with a live
  readiness indicator and placeholder stat tiles in the intelligence-dark
  theme.
- All Phase 1 tests pass in `conda fastapi_setup`.
- `.env.example` has placeholders only; real `.env` is gitignored; no
  secret reachable from the frontend bundle.
- Stub abstractions (`BaseProvider`, `Entity`/`Evidence`/`Relationship`,
  repository base) exist and are imported by at least one test to prove the
  contract compiles.
- Committed with a descriptive message per the project's git conventions.

---

## 9. Risks & Open Items

- **pgvector absent on host PG** — mitigated above; Phase 8 prerequisite.
- **Driver choice** — `psycopg` v3 async is less battle-tested than
  asyncpg for some; both are installed, so swapping `DATABASE_URL` to
  `+asyncpg` is a one-line fallback if issues arise.
- **Full containerization of backend/frontend** — deferred; a
  `backend.Dockerfile` is scaffolded but the dev loop stays host-based per
  operator preference.
