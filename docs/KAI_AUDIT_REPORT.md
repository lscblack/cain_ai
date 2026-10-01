# KAI Implementation Audit

**Audit date:** 2026-10-01
**Git commit:** `ce5f7ac` (branch `main`, working tree clean)
**Environment:** Linux, Python 3.11.13 (conda `fastapi_setup`), Node 24 / pnpm 11,
PostgreSQL 17.7 (host), Redis 7 (host), no GPU (InsightFace on CPU).
**Live instances during audit:** backend `http://127.0.0.1:8001`, frontend
`http://127.0.0.1:5173`.

> Method: evidence-based. Every claim below is backed by a command that was run
> against the real codebase and the running stack — not README claims. Where a
> thing could not be exercised, it is marked **NOT VERIFIED** with the reason.

---

## Executive Summary

**Overall status: PARTIALLY COMPLETE (core is functional and real; external
integrations and large-scale performance are incomplete).**

The core platform is genuinely implemented and working, not mocked:

- Backend builds and starts; `/health/ready` → `{"ready":true,"db":"up","redis":"up"}`.
- **152 backend tests pass** (`pytest`), including **real InsightFace/ArcFace**
  detection, compare, and 1:N search on real photo fixtures.
- Frontend `tsc --noEmit` passes; `pnpm build` produces a bundle; all 14 pages
  are wired to real endpoints.
- Database migrations apply cleanly (4 migrations); data persists across restart.
- SSRF protection, security headers, login rate-limiting, argon2 hashing,
  upload limits are present and tested.

The gaps are where the spec reaches external, key-gated, or scale-dependent
territory: reverse-image discovery has a framework but only one (unconfigured)
adapter; maps/aviation/maritime/satellite/weather/CCTV layers are not built;
phone/email/username lack public-web-source search and PhoneInfoga; the face
index uses JSON embeddings + linear numpy cosine (correct, but not ANN/pgvector
for millions of faces); no benchmarks were run at scale.

**No critical-failure conditions are present** (build works, backend starts,
migrations pass, auth works, face/crawler/phone are real, evidence persists,
no API keys exposed, core tests pass, SSRF protected).

## Score

**128 / 200** — see §Scoring. Core categories score high; external-discovery,
maps breadth, and performance-at-scale drag the total down.

---

## Critical Problems (most important first)

1. **DB password committed as a default value.** `YourStrongPassword` (the
   operator's real local DB password) appears as a hardcoded fallback in
   `backend/tests/conftest.py:19`, `scripts/dev_setup.sh`, and a commented line
   in `docker-compose.yml`. The real `.env` is correctly gitignored, but these
   defaults leak the value into version control. **Severity: HIGH** (local-only
   credential, but should never be in git). Fix: read from env with no secret
   default.
2. **No reverse-image discovery adapters beyond one unconfigured SerpAPI stub.**
   Google Lens / Yandex / Bing / TinEye / Baidu adapters and the candidate
   download→verify→dedupe pipeline (spec §7 Mode A) are not implemented.
   **Severity: MEDIUM** (feature gap, honestly reported as UNAVAILABLE).
3. **Face index will not scale to the spec's 1M–10M target** as built (JSON
   embeddings + full linear scan per query). Correct and fast for thousands;
   needs pgvector/Qdrant + ANN for the stated scale. **Severity: MEDIUM.**
4. **`sqlmodel 0.0.38` requires `SQLAlchemy<2.1` but the env has `2.1.0`.** Works
   today (all tests pass) but is an unsupported combination that could break on
   upgrade. **Severity: LOW–MEDIUM.**

---

## Feature Matrix

| Area | Status | Evidence | Tests | Problems |
|------|--------|----------|-------|----------|
| Architecture | IMPLEMENTED | FastAPI+SQLModel+PG+Redis+SSE; 40 routes; migrations | yes | No containerized backend; docker-compose v1 only; background-tasks not Celery |
| Authentication | IMPLEMENTED | JWT+argon2, register self-locks, audit, rate-limit | test_auth, test_security, test_hardening | single-operator by design; no refresh token |
| Investigation system | IMPLEMENTED | CRUD + entities/evidence/relationships + export | test_investigations_api | no GET /relationships list endpoint (graph covers it) |
| Universal search | IMPLEMENTED | detect + /search over corpus | test_detect, test_search_api | local corpus only (by design for Phase 3) |
| Face detection | IMPLEMENTED | InsightFace buffalo_l, real detect | test_face_api (real model) | CPU only |
| Face embeddings | IMPLEMENTED | 512-d ArcFace, model+version stored, hashes | test_face_api | stored as JSON (no pgvector) |
| Local face search (1:N) | IMPLEMENTED | numpy cosine, bands, SSE stream | test_face_api, SSE test | linear scan (no ANN) |
| Global face discovery | PARTIAL | provider framework + SerpAPI adapter only | test_reverse_image | no Yandex/Bing/TinEye/Baidu; no download+verify; needs key |
| Crawler | IMPLEMENTED | BFS, SSRF, robots, depth/pages, dedup, incremental | test_crawl_runner, test_crawler_extract | no concurrency pool / cancel / scheduler |
| Incremental indexing | IMPLEMENTED | content-hash skip-unchanged | test_crawl_runner::incremental | — |
| Phone intelligence | PARTIAL | libphonenumber: E.164/region/carrier/type/variants | test_phone_* | no PhoneInfoga, no public-web search |
| Email intelligence | PARTIAL | DNS/MX/SPF/DMARC, gravatar, usernames | test_email_* | no DKIM (needs selector), no breach/web search |
| Username intelligence | IMPLEMENTED | concurrent public-profile checks | test_username_* | live-site dependent; not persisted to case automatically |
| Entity graph | IMPLEMENTED | model + co-occurrence correlation + SVG graph | test_correlate, test_correlations_api | co-occurrence only |
| Evidence system | IMPLEMENTED | provenance fields, persistence, JSON/CSV export | test_investigations_api, test_hardening_export | — |
| Maps | PARTIAL | Leaflet renders located entities + config endpoint | test_maps_timeline_api | no aircraft/vessel/satellite/weather/CCTV layers |
| AI analyst | PARTIAL | OpenAI/OpenRouter abstraction, grounded prompt | test_analyst_api | needs key; no local-model fallback |
| Power Ups | PARTIAL | status/health/configured, no secrets | test_powerup_api | no enable/disable persistence; no usage metrics |
| Security | IMPLEMENTED | SSRF, headers, rate-limit, argon2, upload caps | test_net_ssrf, test_hardening | DB password in committed defaults (see Critical #1) |
| Performance | NOT VERIFIED | no scale benchmarks run | — | linear face scan; no ANN; not measured at 1k/1M |
| Documentation | PARTIAL | README + specs + plans | — | no THIRD_PARTY_LICENSES.md; no ESLint; thin troubleshooting |

---

## Tests Executed

| Command | Result |
|---------|--------|
| `git status` | clean, `main`, commit `ce5f7ac` |
| `pip check` | pre-existing unrelated conflicts (platformio, google-ai, grpcio); **sqlmodel↔SQLAlchemy 2.1 mismatch** (relevant) |
| `pytest -p no:cacheprovider` | **152 passed, 8 warnings, 65s** |
| `tsc --noEmit` (pnpm typecheck) | **exit 0** |
| `pnpm build` | success (~500 KB JS bundle) |
| `curl /health/ready` | `{"ready":true,"db":"up","redis":"up"}` |
| `curl /openapi.json` | 40 routes enumerated |
| real-model face check | same image cos=1.0, Lincoln vs Einstein cos=0.04 |
| secret grep (`git grep sk-/API_KEY/...`) | no API keys; DB password in 3 default fallbacks |
| `git ls-files | grep .env$` | no `.env` committed |

## Failed Tests

None. (152/152 pass.)

## Security Findings

- **HIGH** — DB password `YourStrongPassword` present as hardcoded default in
  `backend/tests/conftest.py`, `scripts/dev_setup.sh`, `docker-compose.yml`
  (commented). Not an API key and local-only, but must not be in git.
- **MEDIUM** — `sqlmodel`/`SQLAlchemy` version mismatch (supply-chain/stability).
- **LOW** — No ESLint; no automated frontend security linting.
- **LOW** — No CSRF tokens, but auth is bearer-token (not cookie) so CSRF risk is
  low; acceptable for the single-operator local model.
- **PASS** — SSRF validation blocks loopback/RFC1918/link-local/metadata (13
  tests); applied in crawler + username + source creation. Security headers
  present (verified `x-frame-options: DENY`). Login rate-limited. argon2 hashing.
  Upload type/size limits on face endpoints. No secrets in frontend bundle
  (frontend only receives `VITE_API_URL`).

## Missing Features (exact)

- Reverse-image adapters: Google Lens, Yandex, Bing Visual Search, TinEye, Baidu
  (only a SerpAPI stub exists); candidate-image download + local face
  verification + dedup pipeline (spec §7 Mode A).
- PhoneInfoga integration; phone public-web source search.
- Email DKIM, breach-status providers, public-web search.
- Map layers: aircraft (OpenSky), vessels (AISStream), satellites, weather
  (Windy), CCTV — only located-entity markers exist.
- Crawler: scheduled/periodic crawls, stop/resume, concurrency pool, cancellation.
- Power Up: persistent enable/disable toggles, per-provider usage metrics,
  rate-limit display.
- AI: local-model fallback provider.
- Worker system (Celery/RQ): crawls run as FastAPI BackgroundTasks, not a
  separate scalable worker (acceptable for local, not for scale).
- `docs/THIRD_PARTY_LICENSES.md`; ESLint; frontend tests; observability/admin
  panel (CPU/RAM/queue depth).

## Broken Features

None found. All implemented endpoints return real data or an explicit
UNAVAILABLE state.

## Partial Features

Global face discovery, phone, email, maps, AI analyst, Power Ups, local index at
scale — see matrix. All are honestly gated (UNAVAILABLE without keys) rather than
faked.

## Dead Code / Mock Features

- No fabricated result data found in production paths. `return []` occurrences are
  legitimate (empty-corpus search, invalid-username, unconfigured provider).
- `frontend` calls `GET /investigations/{id}/relationships` with a `.catch(()=>[])`
  fallback, but **that route does not exist** — currently harmless (graph endpoint
  supplies edges) but is dead client code to clean up.

## Performance Measurements

**NOT VERIFIED at scale.** No 100/1k/1M-face benchmarks were run during this
audit. Observations: single-face detect+embed ≈ 0.3–1s on CPU (from test
timings); 1:N search is an O(n) numpy loop — fine for thousands, inadequate for
the spec's 1M–10M target without ANN (pgvector/Qdrant/Milvus).

## Recommended Fix Order

1. **P0** Remove the DB password default from `conftest.py`, `dev_setup.sh`,
   `docker-compose.yml`; require it from env.
2. **P1** Resolve the `sqlmodel`/SQLAlchemy version mismatch (pin SQLAlchemy
   <2.1 or move off SQLModel for the constrained models).
3. **P1** Add `docs/THIRD_PARTY_LICENSES.md` (InsightFace/buffalo_l, phonenumbers,
   dnspython, FastAPI, etc.).
4. **P2** Introduce pgvector (or Qdrant) for face embeddings + ANN before growing
   the index.
5. **P2** Build the reverse-image candidate download→verify→dedup pipeline and at
   least one more adapter.
6. **P3** Map layers, PhoneInfoga, Power Up toggles, worker queue, observability,
   ESLint + frontend tests.

## Final Assessment

KAI is a **real, working OSINT platform core**, not a demo: authentication,
investigations/evidence/relationships, universal search, genuine ArcFace face
detection/compare/1:N search with live SSE, an SSRF-guarded incremental crawler
that indexes faces, phone/email/username intelligence, correlation + graph, map,
timeline, AI-analyst framework, and evidence export — all backed by 152 passing
tests and verified against a live stack.

To be considered *complete against the full spec*, it still needs: the external
reverse-image discovery pipeline and adapters, scale-grade vector search
(pgvector/ANN), the additional map/geo provider layers, PhoneInfoga/public-web
search for phone/email, a real worker queue + scheduler for continuous crawling,
observability, the licenses doc, and the credential-in-defaults fix. These are
additive; none require rearchitecting the core.
