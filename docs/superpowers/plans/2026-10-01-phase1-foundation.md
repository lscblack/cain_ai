# KAI Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a runnable KAI foundation — infra, FastAPI backend with single-operator JWT auth, core abstraction stubs, SSRF validator, and a React dashboard — verified end-to-end with tests.

**Architecture:** FastAPI (async, SQLModel/SQLAlchemy 2.1 over host Postgres via psycopg v3) + Redis. Single-operator auth (first-run register self-locks, JWT bearer, argon2). Core seams (`BaseProvider`, `Entity`/`Evidence`/`Relationship`, repository base) defined as stubs so later phases implement, not rewrite. React/TS/Tailwind/Vite frontend with an intelligence-dark theme.

**Tech Stack:** Python 3.11 (conda `fastapi_setup`), FastAPI, SQLModel, SQLAlchemy 2.1, Alembic, psycopg v3, redis + fakeredis, argon2-cffi, python-jose, pytest/pytest-asyncio/httpx; pnpm + Vite + React + TypeScript + Tailwind + framer-motion + lucide-react.

**Spec:** `docs/superpowers/specs/2026-10-01-phase1-foundation-design.md`

## Global Constraints

- Backend runs in conda env `fastapi_setup`; no new Python installs.
- DB driver `postgresql+psycopg`; default DB host Postgres 17.7, database `kai`.
- Secrets live only in gitignored `.env`; `.env.example` has placeholders only; frontend gets only `VITE_API_URL`.
- Guardrails are acceptance criteria: SSRF validator present; auth cannot be bypassed; no "confirmed identity" language anywhere in UI.
- Commit messages: `feat(scope): ...` / `chore(scope): ...`, ending with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Review Focus

- **Malformed/absent JWT** (missing header, garbage token, `alg=none`): `/auth/me` and protected routes must 401, never 500 or accept.
- **Expired JWT**: must 401 with a clear code, not silently accepted.
- **Second registration attempt** once an operator exists: must 403 `registration_closed`, never create a second user or leak which part failed.
- **SSRF via DNS**: a hostname whose DNS resolves to a private/loopback/link-local IP (incl. 169.254.169.254) must be rejected even though the hostname looks public.
- **`/health/ready` when a dependency is down** (Postgres or Redis unreachable): must report that dependency unhealthy and overall not-ready, not crash.

---

## Task 1: Repo scaffolding, env, gitignore

**Files:**
- Create: `.gitignore`, `.env.example`, `backend/pyproject.toml`, `backend/app/__init__.py`, `README.md`, `scripts/dev_setup.sh`
- Create: `backend/app/core/__init__.py`, `backend/app/database/__init__.py`, `backend/app/api/__init__.py`, `backend/app/providers/__init__.py`, `backend/tests/__init__.py`

- [ ] **Step 1:** Write `.gitignore` (`.env`, `*.key`, `credentials/`, `secrets/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `node_modules/`, `dist/`, `.venv/`, `data/`, `*.log`).
- [ ] **Step 2:** Write `.env.example` with placeholders only (APP_ENV, APP_SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES, DATABASE_URL, REDIS_URL, CORS_ORIGINS). No real password.
- [ ] **Step 3:** Create package dirs with `__init__.py`; `backend/pyproject.toml` (metadata + pytest config: `asyncio_mode = auto`).
- [ ] **Step 4:** `README.md` with run instructions; `scripts/dev_setup.sh` (createdb kai, alembic upgrade, hints).
- [ ] **Step 5:** Commit `chore(phase1): scaffold repo, env, gitignore`.

## Task 2: Config + logging

**Files:**
- Create: `backend/app/core/config.py`, `backend/app/core/logging.py`, `backend/tests/test_config.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings) with `app_env`, `app_secret_key`, `access_token_expire_minutes`, `database_url`, `redis_url`, `cors_origins: list[str]`; singleton `get_settings()`. `configure_logging()`.

- [ ] **Step 1:** Test: `get_settings()` reads env vars (monkeypatch) and parses `CORS_ORIGINS` comma string into a list.
- [ ] **Step 2:** Run test → FAIL.
- [ ] **Step 3:** Implement `config.py` (BaseSettings, `.env`, field validator splitting CORS); `logging.py` (dictConfig, level from env).
- [ ] **Step 4:** Run test → PASS.
- [ ] **Step 5:** Commit `feat(core): add settings and logging`.

## Task 3: Security primitives (hashing + JWT)

**Files:**
- Create: `backend/app/core/security.py`, `backend/tests/test_security.py`

**Interfaces:**
- Produces: `hash_password(pw)->str`, `verify_password(pw, hash)->bool`, `create_access_token(sub, expires_delta=None)->str`, `decode_token(token)->dict` (raises `TokenError` on invalid/expired).

- [ ] **Step 1:** Tests: hash round-trip true; wrong pw false; token decode returns `sub`; tampered token raises; expired token (negative delta) raises; `alg=none` token rejected.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement with argon2-cffi `PasswordHasher` and python-jose HS256; `decode_token` pins `algorithms=["HS256"]`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(core): add password hashing and JWT security`.

## Task 4: SSRF-safe URL validator

**Files:**
- Create: `backend/app/core/net.py`, `backend/tests/test_net_ssrf.py`

**Interfaces:**
- Produces: `validate_public_url(url, *, resolver=None)->SafeUrl` raising `UnsafeUrlError`; `SafeUrl` dataclass (scheme, host, resolved_ips). `resolver` injectable for tests.

- [ ] **Step 1:** Tests (inject a fake resolver): public IP allowed; `http://localhost` blocked; `127.0.0.1`, `10.0.0.5`, `192.168.1.1`, `172.16.0.1`, `169.254.169.254` blocked; `::1` and `fc00::1` blocked; `file://` and `ftp://` scheme blocked; hostname resolving to one public + one private IP → blocked (any-private rule).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement: parse URL, require http/https, resolve host (injected resolver default = socket.getaddrinfo), check every IP with `ipaddress` for is_private/is_loopback/is_link_local/is_reserved/unspecified.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(core): add SSRF-safe URL validator`.

## Task 5: DB base, session, models

**Files:**
- Create: `backend/app/database/base.py`, `backend/app/database/session.py`, `backend/app/database/models/__init__.py`, `backend/app/database/models/user.py`, `backend/app/database/models/audit.py`, `backend/tests/conftest.py`, `backend/tests/test_models.py`

**Interfaces:**
- Produces: `UUIDTimestampMixin`; `User(id, email, password_hash, created_at, updated_at)`; `AuditLog(id, created_at, actor_id, action, detail, ip)`; `engine`, `async_session_maker`, `get_session()` dependency. `conftest`: `db_session` fixture (disposable `kai_test` db, create_all/drop), `client` fixture (httpx AsyncClient + fakeredis override).

- [ ] **Step 1:** Test: create a `User` and `AuditLog` row via `db_session`, read back; email unique constraint raises on duplicate.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement mixins, models, async engine/session; `conftest` building a test engine against `kai_test` (create/drop all per session) and a fakeredis fixture.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(db): add base mixins, user/audit models, async session`.

## Task 6: Repositories

**Files:**
- Create: `backend/app/database/repositories/__init__.py`, `backend/app/database/repositories/base.py`, `backend/app/database/repositories/user_repo.py`, `backend/app/database/repositories/audit_repo.py`, `backend/tests/test_repositories.py`

**Interfaces:**
- Produces: `BaseRepository[T]` (`get`, `list`, `add`, `count`); `UserRepository.get_by_email`, `.count`; `AuditRepository.record(action, actor_id=None, detail=None, ip=None)`.

- [ ] **Step 1:** Tests: `UserRepository.count()==0` initially; add user, `get_by_email` returns it; `AuditRepository.record` persists a row.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement generic repo + user/audit repos.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(db): add repository layer`.

## Task 7: Stub abstractions (provider + entity contracts)

**Files:**
- Create: `backend/app/providers/base.py`, `backend/app/database/entities.py`, `backend/tests/test_stubs.py`

**Interfaces:**
- Produces: `BaseProvider` ABC (`name`, `type`, `enabled`, async `health_check`, `search`, `enrich`, `rate_limit`, `configuration`); Pydantic contract models `EntityContract`, `EvidenceContract` (id, type, source_url, collected_at, first_seen, last_seen, hash, confidence, raw_metadata, processed_metadata), `RelationshipContract` (source_id, target_id, rel_type, source_url, observed_at, confidence, evidence_excerpt).

- [ ] **Step 1:** Tests: `BaseProvider` cannot be instantiated (abstract); a trivial subclass implementing the methods can; `EvidenceContract` requires `source_url` and `collected_at` (validation error without them).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement ABC + contract models.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(core): add provider and entity/evidence contract stubs`.

## Task 8: Alembic migrations

**Files:**
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial.py`

- [ ] **Step 1:** `alembic init`-style config pointing at `DATABASE_URL` (sync psycopg for migrations), target metadata = SQLModel metadata.
- [ ] **Step 2:** Autogenerate/handwrite `0001_initial` creating `users` + `audit_logs`.
- [ ] **Step 3:** Run `alembic upgrade head` against `kai` → verify tables exist (`\dt`).
- [ ] **Step 4:** Commit `feat(db): add alembic migrations for users and audit_logs`.

## Task 9: Auth API

**Files:**
- Create: `backend/app/api/deps.py`, `backend/app/api/auth.py`, `backend/app/schemas/auth.py`, `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: security (Task 3), repos (Task 6), session (Task 5).
- Produces: router `/auth` with `POST /register`, `POST /login`, `GET /me`; `get_current_operator` dependency; schemas `RegisterIn`, `LoginIn`, `TokenOut`, `OperatorOut`.

- [ ] **Step 1:** Tests (via httpx client + test db): register when empty → 201 + token; second register → 403 `registration_closed`; login good → 200 token; login wrong pw → 401; `/me` no token → 401; `/me` bad token → 401; `/me` valid → 200 email; audit rows for register/login/login_failed.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement schemas, deps (`get_current_operator` using `decode_token` + user lookup, always 401 on any failure), auth router (register gated on `UserRepository.count()==0`; login always runs a hash verify to reduce timing leak).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(auth): single-operator register/login/me with audit`.

## Task 10: Health API + app factory

**Files:**
- Create: `backend/app/api/health.py`, `backend/app/main.py`, `backend/tests/test_health.py`

**Interfaces:**
- Consumes: session, redis, settings.
- Produces: `create_app()`; `/health` (liveness), `/health/ready` (checks `SELECT 1` + redis `PING`, returns `{db, redis, ready}`).

- [ ] **Step 1:** Tests: `/health` → 200 `{"status":"ok"}`; `/health/ready` with working test db + fakeredis → `ready: true`; simulate redis failure (patch) → `ready: false`, `redis:"down"`, HTTP 503.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `main.create_app()` (CORS from settings, mount auth+health routers, logging on startup) and health router.
- [ ] **Step 4:** Run → PASS; also run full backend suite `pytest -q`.
- [ ] **Step 5:** Commit `feat(api): add health endpoints and app factory`.

## Task 11: Frontend scaffold + theme

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.ts`, `frontend/postcss.config.js`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/styles/theme.css`, `frontend/.env.example`

- [ ] **Step 1:** `pnpm` project with React/TS/Vite/Tailwind/framer-motion/lucide-react; Tailwind configured with theme tokens (bg `#0a0b0d`, panel `#111622`, red `#e5484d`, green `#30a46c`, amber `#f5a623`, mono font).
- [ ] **Step 2:** `theme.css` defines CSS custom properties; base dark background on `body`.
- [ ] **Step 3:** `pnpm install` then `pnpm build` → succeeds (verification).
- [ ] **Step 4:** Commit `feat(frontend): scaffold vite+react+tailwind with intelligence-dark theme`.

## Task 12: Frontend auth + API client

**Files:**
- Create: `frontend/src/lib/api.ts`, `frontend/src/lib/auth.tsx`, `frontend/src/types.ts`

**Interfaces:**
- Produces: `api.get/post` (bearer from localStorage, typed errors); `AuthProvider`, `useAuth()` (`operator`, `login`, `logout`, `loading`, `registrationOpen`).

- [ ] **Step 1:** Implement `api.ts` (base `VITE_API_URL`, attach token, parse `{detail}` errors).
- [ ] **Step 2:** Implement `auth.tsx` (token in localStorage; `me()` on mount; `login` posts and stores token; detect registration-open by probing).
- [ ] **Step 3:** `pnpm build` → succeeds.
- [ ] **Step 4:** Commit `feat(frontend): add API client and auth context`.

## Task 13: Login + Dashboard pages, wire up

**Files:**
- Create: `frontend/src/pages/Login.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/AppShell.tsx`, `frontend/src/components/StatusIndicator.tsx`
- Modify: `frontend/src/App.tsx` (routing/guard)

- [ ] **Step 1:** `Login` (email/password → login; first-run "create operator" calling `/auth/register` when registration open).
- [ ] **Step 2:** `AppShell` (sidebar/topbar, KAI wordmark "Knowledge • Analysis • Intelligence"), `StatusIndicator` polling `/health/ready` → green/red dot "SYSTEM ONLINE".
- [ ] **Step 3:** `Dashboard` (protected; operator email; stat tiles Faces/Phones/Emails/Sources = 0/—; placeholder "LIVE INTELLIGENCE MAP" panel). `App` guards routes by `useAuth`.
- [ ] **Step 4:** `pnpm build` → succeeds.
- [ ] **Step 5:** Commit `feat(frontend): add login and dashboard with live readiness`.

## Task 14: End-to-end verification + infra compose

**Files:**
- Create: `docker-compose.yml`, `infra/docker/backend.Dockerfile`
- Modify: `README.md` (final run steps)

- [ ] **Step 1:** `docker-compose.yml`: `redis:7` service (named volume); commented optional `pgvector/pgvector:pg17` postgres service with note. `backend.Dockerfile` for later use.
- [ ] **Step 2:** Bring up: `docker compose up -d redis`; `createdb kai`; `alembic upgrade head`; start `uvicorn`; `curl /health/ready` → ready true.
- [ ] **Step 3:** `pnpm dev` + manual/automated check: register → login → dashboard green. Capture outcome.
- [ ] **Step 4:** Run full backend `pytest -q` → all green; `pnpm build` green.
- [ ] **Step 5:** Update README with verified steps; commit `chore(phase1): add compose, verify end-to-end foundation`.

---

## Self-Review

- **Spec coverage:** layout (T1), config/logging (T2), security (T3), SSRF (T4), db/models/session (T5), repos (T6), stubs (T7), migrations (T8), auth (T9), health+factory (T10), frontend theme/auth/pages (T11-13), compose+e2e (T14). All §2 in-scope items covered.
- **Placeholder scan:** none — each task has concrete interfaces and test intents.
- **Type consistency:** `get_current_operator`, `decode_token`, `UserRepository.count/get_by_email`, `AuditRepository.record` names consistent across T3/T6/T9.
- **Review Focus:** malformed/expired JWT + 2nd-register → T9 tests; SSRF DNS → T4 tests; ready-when-down → T10 tests. All owned.
