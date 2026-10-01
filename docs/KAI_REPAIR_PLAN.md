# KAI Repair Plan

Derived from `KAI_AUDIT_REPORT.md` (commit `ce5f7ac`). Priorities:
**P0** critical · **P1** major · **P2** important · **P3** polish.
Nothing here requires rearchitecting the core.

---

## P0 — Critical

### P0.1 Remove DB password from committed defaults
- **Problem:** `YourStrongPassword` is a hardcoded default in
  `backend/tests/conftest.py:19`, `scripts/dev_setup.sh`, `docker-compose.yml` (comment).
- **Root cause:** convenience defaults baked in instead of required env.
- **Files:** `backend/tests/conftest.py`, `scripts/dev_setup.sh`, `docker-compose.yml`.
- **Required change:** `conftest` reads `TEST_DATABASE_URL` from env and skips (or
  xfails) DB tests if unset; `dev_setup.sh` requires `DB_PASSWORD` (no default);
  remove the literal from the compose comment. Rotate the local DB password after.
- **Test required:** `git grep -n YourStrongPassword` returns nothing outside
  `.env`; full suite still passes with `TEST_DATABASE_URL` exported.
- **Expected result:** no credential value in version control.

---

## P1 — Major

### P1.1 Fix sqlmodel / SQLAlchemy version mismatch
- **Problem:** `sqlmodel 0.0.38` requires `SQLAlchemy<2.1`; env has `2.1.0`.
- **Root cause:** env pre-provisioned with newer SQLAlchemy.
- **Files:** `backend/requirements.txt` (+ env).
- **Required change:** pin `SQLAlchemy>=2.0.14,<2.1` and reinstall, OR upgrade to a
  sqlmodel release that supports 2.1 when available.
- **Test required:** `pip check` shows no sqlmodel/SQLAlchemy conflict; suite green.
- **Expected result:** supported, reproducible dependency set.

### P1.2 Third-party licenses document
- **Problem:** no `docs/THIRD_PARTY_LICENSES.md` (audit §31).
- **Files:** new `docs/THIRD_PARTY_LICENSES.md`.
- **Required change:** list InsightFace + buffalo_l model (MIT / non-commercial
  research note), onnxruntime, phonenumbers, dnspython, FastAPI, SQLModel,
  Leaflet, CARTO tiles, etc., with license + version + what is used.
- **Test required:** manual review; link from README.
- **Expected result:** license provenance documented. **Note:** confirm the
  InsightFace model licence permits the intended use before any non-research use.

### P1.3 Remove dead `relationships` client call
- **Problem:** frontend calls non-existent `GET /investigations/{id}/relationships`.
- **Files:** `frontend/src/lib/investigations.ts` (+ optionally add the route).
- **Required change:** either add a real `GET .../relationships` endpoint
  (symmetry with entities/evidence) or drop the client method.
- **Test required:** new API test if endpoint added; `tsc` clean.
- **Expected result:** no dead client code.

---

## P2 — Important

### P2.1 pgvector + ANN for face search at scale
- **Problem:** JSON embeddings + O(n) numpy scan won't meet 1M–10M target.
- **Root cause:** pgvector absent on host PG; deferred by design.
- **Files:** new migration, `faces.embedding` → `vector(512)`,
  `app/intelligence/face/*`, `app/api/faces.py` search path.
- **Required change:** enable `CREATE EXTENSION vector` (host install or the
  `pgvector/pgvector` compose service), store embeddings as `vector`, add an
  IVFFlat/HNSW index, switch 1:N search to `ORDER BY embedding <=> :q`.
- **Test required:** search correctness parity test (same top-1 as numpy on
  fixtures); a seeded-1k benchmark recorded in the report.
- **Expected result:** sub-linear search; measured latency at 1k+.

### P2.2 Reverse-image discovery pipeline + adapters
- **Problem:** only an unconfigured SerpAPI stub; no download→verify→dedup.
- **Files:** `app/providers/reverse_image.py`, new `app/intelligence/face/discover.py`,
  `app/api/faces.py` (`/discover` endpoint, SSE), Face page Mode A.
- **Required change:** given a query face, call configured providers → collect
  candidate image URLs → SSRF-guarded download → detect+embed → compare to query →
  dedup (sha256/phash) → stream results. Add ≥1 more adapter (e.g. TinEye API).
- **Test required:** full pipeline with a mocked provider + local fixtures (offline).
- **Expected result:** global discovery works when a key is set; UNAVAILABLE otherwise.

### P2.3 Worker queue + crawl scheduling / control
- **Problem:** crawls run as BackgroundTasks; no scheduler/stop/resume/concurrency.
- **Files:** `app/workers/*` (new), Celery or arq on Redis; `app/api/sources.py`.
- **Required change:** move crawl to a worker; add schedule execution
  (hourly/6h/daily/weekly), pause/resume, bounded concurrency, cancellation.
- **Test required:** enqueue + status transition tests with a fake broker.
- **Expected result:** continuous indexing without blocking the API process.

### P2.4 Phone/Email public-source enrichment
- **Problem:** no PhoneInfoga, no public-web/breach search.
- **Files:** `app/providers/phoneinfoga.py` (adapter), email breach adapter.
- **Required change:** wrap PhoneInfoga behind the provider interface (key/binary
  gated → UNAVAILABLE otherwise); add a breach provider adapter.
- **Test required:** adapter tests with mocked responses.
- **Expected result:** richer, still-honest phone/email results.

---

## P3 — Polish

### P3.1 Map provider layers
- OpenSky (aircraft), AISStream (vessels), Windy (weather), satellite, CCTV —
  each a key-gated layer toggled in the UI; UNAVAILABLE without key.
- Files: `app/providers/{aviation,maritime,satellite,weather,cctv}.py`, MapView layers.

### P3.2 Power Up enable/disable + usage
- Persist per-provider enabled state and request counts (Redis), show rate limits.
- Files: `app/api/powerup.py`, a small `provider_runs` store, PowerUp page.

### P3.3 Observability / admin panel
- CPU/RAM, queue depth, worker status, storage usage (audit §39).

### P3.4 Tooling & tests
- ESLint config; a few frontend component tests; expand backend edge cases.

### P3.5 Full containerization
- Backend/frontend Dockerfiles wired into compose; health checks; upgrade host to
  `docker compose` v2 or document v1 usage.

### P3.6 AI local-model fallback
- Add a `LocalModelProvider` (e.g., Ollama) behind `AIProvider`.

---

## Suggested execution order

P0.1 → P1.1 → P1.2 → P1.3 → P2.1 → P2.2 → P2.3 → P2.4 → P3.*

Each item is independently shippable with its own test; do them as separate
commits so the working core stays green throughout.
