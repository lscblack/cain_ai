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
`docs/superpowers/plans/` (implementation plans). 150+ backend tests.

- **Phase 1 — Foundation:** infra, single-operator JWT auth, core abstractions, SSRF validator, dashboard. ✅
- **Phase 2 — Investigations/cases:** entities, evidence, relationships, graph; CASE-YYYY-NNNN. ✅
- **Phase 3 — Universal search:** type detection + local-corpus search. ✅
- **Phase 4 — Phone intelligence:** libphonenumber analysis + variants. ✅
- **Phase 5 — Email intelligence:** DNS/MX/SPF/DMARC, Gravatar, derived usernames. ✅
- **Phase 6 — Username intelligence:** public-platform presence checks. ✅
- **Phase 7 — Evidence graph:** co-occurrence correlation + interactive graph. ✅
- **Phase 8 — Face detection + embeddings:** InsightFace/ArcFace (CPU), compare + 1:N search. ✅
- **Phases 9–10 — Local index + crawler:** incremental SSRF-guarded crawler, dedup, face indexing. ✅
- **Phase 11 — Reverse-image discovery:** key-gated provider framework (SerpAPI). ✅
- **Phase 12 — Live face search:** SSE streaming progress. ✅
- **Phase 13 — Maps:** Leaflet geographic view of located entities. ✅
- **Phase 14 — Power Up:** provider status panel. ✅
- **Phase 15 — AI analyst:** OpenRouter/OpenAI-compatible, evidence-grounded. ✅
- **Phase 16 — Timeline:** chronological observation view. ✅
- **Phase 18 — Hardening:** security headers, login rate-limit, evidence export (JSON/CSV). ✅
- **KAI Chat + Security Tools:** local `kai-security` (Ollama) chat with persistent
  conversations and streaming, plus a backend-managed registry of real Ubuntu
  security tools (DNS/WHOIS/HTTP-headers/TLS/nmap/log-analysis/CVE research) that
  the model can select and run under strict controls, a controlled apt install
  approval workflow, and a Security Console UI. ✅

- **Voice Intelligence:** local voice cloning, text-to-speech and live voice conversion with a
  PipeWire virtual microphone. See [docs/VOICE_INTELLIGENCE.md](docs/VOICE_INTELLIGENCE.md). On a CPU
  live conversion runs a few seconds behind; real-time speed on a GPU is not yet verified. ✅

External providers (reverse-image, AI, map tiles) report **UNAVAILABLE** until
their API keys are set in `.env` — KAI never fabricates results.

## KAI Chat & security tools (local model)

KAI talks to a local **Ollama** server running the customised `kai-security`
model (configure with `KAI_OLLAMA_MODEL`, default `kai-security`;
`OLLAMA_BASE_URL` defaults to `http://127.0.0.1:11434`). KAI **never silently
falls back to a cloud model** — if Ollama is down or the model is missing, the
chat and the status badge say exactly what to fix.

Open **KAI Chat** to converse (streaming; conversations persist). With the
*tools* toggle on, the model can select and run real host tools through a
hardened backend:

- **Execution is argv-only** (`subprocess`, never a shell), with a sanitised
  environment, per-run timeout, output caps, rate limiting, secret redaction,
  and an audit log. The model never gets a shell or root.
- Because `kai-security` has no native tool-calling, KAI uses a **validated JSON
  orchestration protocol** — the model proposes a tool call, the backend
  validates + executes it, and the real result is fed back. Nothing is faked.
- **Active** operations (e.g. `nmap`) are refused unless the target is on the
  operator's **authorized-targets** list (passive OSINT needs no entry).
- The **Security Console** shows tool inventory (live host state), execution
  history, authorized targets, structured findings, and the install workflow.

### Controlled package installs

The model can *request* a missing tool; only an operator *approves*, and nothing
is marked installed until it verifies on the real host. Installs run one fixed
argv — `apt-get install -y --no-install-recommends <validated-package>` — via a
scoped privileged helper (`TOOL_INSTALL_HELPER`, default `sudo`). For real
execution, grant a **narrow** NOPASSWD rule (installs otherwise fail honestly
with `sudo_needs_password`):

```sudoers
# /etc/sudoers.d/kai-apt   (edit with: sudo visudo -f /etc/sudoers.d/kai-apt)
# Replace <user> with the account running the backend.
<user> ALL=(root) NOPASSWD: /usr/bin/apt-get install -y --no-install-recommends *
```

Alternatively set `TOOL_INSTALL_HELPER=pkexec` for a desktop prompt, or
`TOOL_INSTALL_ENABLED=false` to record approvals without executing. KAI does
**not** add Kali/Parrot repos, install RPMs, or disable signature verification.

Requires the dnsutils/whois/curl/openssl/nmap/systemd/ufw packages for the
built-in tools (most ship with Ubuntu). CVE research uses the keyless OSV.dev
public API.

## Architecture

- **Backend:** FastAPI + SQLModel/SQLAlchemy 2.1 (async, psycopg v3) over
  PostgreSQL, Redis for jobs/cache.
- **Frontend:** React + TypeScript + Tailwind + Vite (intelligence-dark theme).
- **ML/crawl/providers:** added in later phases behind stable interfaces.

## Running Phase 1 (local dev)

Prerequisites: a local PostgreSQL 17 at `127.0.0.1:5432`, Docker (for Redis),
the conda env `fastapi_setup`, and `pnpm`.

```bash
# 1. Infra: Redis (Postgres is your host instance).
#    This machine has docker-compose v1, so use the hyphenated command.
#    If a Redis is already listening on 6379, you can skip this.
docker-compose up -d redis

# 2. Config
cp .env.example .env   # then edit credentials/secret

# 3. Database
createdb kai   # or: psql -U postgres -c 'CREATE DATABASE kai;'

# 4. Backend
conda activate fastapi_setup
cd backend
alembic upgrade head
uvicorn app.main:app --reload --app-dir .   # add --port 8001 if 8000 is taken

# 4. Crawl worker (run in a second backend terminal)
python -m app.crawlers.worker

# 5. Frontend (new terminal)
cd frontend
cp .env.example .env   # set VITE_API_URL to match the backend port
pnpm install
pnpm dev
```

Open http://127.0.0.1:5173 → on first run, create the operator account → log
in → the dashboard shows a live system-readiness indicator.

> **Port note:** if `:8000` is already in use by another local app, run the
> backend with `--port 8001` and set `VITE_API_URL=http://127.0.0.1:8001` in
> `frontend/.env`.

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
