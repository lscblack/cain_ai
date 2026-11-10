# GEOINT Phases 1–4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the keyless GEOINT capability on KAI's map — imagery base + layer catalogue, temporal before/after compare, terrain + infrastructure datasets, and annotations saved as Evidence on investigations.

**Architecture:** A new backend `geoint` router exposes a static keyless layer catalogue, an elevation proxy (OpenTopoData, cached), and an evidence-write endpoint that reuses the existing `Evidence` model. A new frontend `geoint/` module (layer catalogue, basemap picker, date-compare control, annotate layer) plugs into the chat `MapCard` and the full-page `MapView`. Imagery/hillshade/GIBS tiles are browser-fetched; only elevation and evidence touch the backend.

**Tech Stack:** FastAPI + async SQLAlchemy/SQLModel + pytest (asyncio_mode=auto) backend; React + TypeScript + Vite + react-leaflet frontend (verified by `tsc --noEmit` + `vite build` — no component test harness in this repo).

**Spec:** `docs/superpowers/specs/2026-11-10-geoint-design.md`

## Global Constraints

- **Keyless-only.** No new API keys, no new env vars, no paid providers. Providers: NASA GIBS, Esri World Imagery, Esri World Hillshade, OpenTopoData, Overpass, OSM, OSRM.
- **No new DB table.** GEOINT annotations are stored in the existing `Evidence` model (`backend/app/database/models/evidence.py`).
- **Evidence `type`** for GEOINT rows is the plain string `"geoint"` written directly on the model — do **not** extend the shared `EntityType` enum.
- **`Evidence.source_url`** must be a clean `https://` provider URL (no `{z}/{x}/{y}`/`{Time}` placeholders); the full templated URL + dates go in `raw_metadata`.
- **Graceful degradation.** Any provider failure leaves the map usable; backend proxy endpoints never return 5xx on upstream failure — they return a handled `{ok: false, reason}`.
- **Auth.** Every new backend route depends on `get_current_operator` and `get_session` (pattern: `backend/app/api/geo.py`).
- **Commits** end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **No changes to Phase 0 behaviour** (tile modes / fullscreen / follow-route already shipped in `MapCard`).

## Review Focus

- A GIBS date with no satellite pass returns empty/transparent tiles — the date/compare control must show a "no imagery this date" hint and keep the other layer, not blank the map. (Task 3, manual verification + code handling.)
- `GET /geoint/elevation` must never 500 on an upstream failure or a malformed `points` arg — it returns a handled `{ok:false}` or 422 and the UI hides the profile. (Task 4 tests.)
- `POST /geoint/evidence` must reject a non-existent `investigation_id` (404) and an invalid GeoJSON FeatureCollection (422) **before** any write, so no partial/orphan `Evidence` row is created. (Task 6 tests.)
- The annotate/draw layer must remove its Leaflet event handlers on unmount and on fullscreen toggle — same class of bug as the Phase 0 geolocation watcher. (Task 7, manual verification.)
- Switching basemaps must not drop an active annotation layer or compare state. (Task 7 / Task 3, manual verification.)

---

### Task 1: Backend — `GET /geoint/layers` catalogue

**Files:**
- Create: `backend/app/api/geoint.py`
- Modify: `backend/app/main.py` (import `geoint` in the api import block ~line 8; `app.include_router(geoint.router)` near the other includes ~line 171)
- Test: `backend/tests/test_geoint_layers.py`

**Interfaces:**
- Produces: router with prefix `/geoint`, tag `geoint`. `GET /geoint/layers` → `{"layers": [LayerDef, ...]}` where `LayerDef = {id: str, kind: "base"|"overlay", label: str, url_template: str, attribution: str, dated: bool, max_zoom: int}`. The catalogue is a module-level constant (static, no secret). Includes at minimum: `osm_dark`, `osm`, `esri_imagery` (base, undated, max_zoom 19), `esri_hillshade` (overlay), and at least two dated GIBS layers (e.g. `gibs_modis_truecolor`, `gibs_viirs_truecolor`) whose `url_template` contains a `{Time}` token and `dated: true`.

- [ ] **Step 1: Write the failing test**

```python
# test_geoint_layers.py
async def test_layers_catalogue_shape(client):
    r = await client.get("/geoint/layers")
    assert r.status_code == 200
    layers = r.json()["layers"]
    assert len(layers) >= 5
    for l in layers:
        assert l["url_template"] and l["attribution"]
        assert l["kind"] in ("base", "overlay")
    dated = [l for l in layers if l["dated"]]
    assert dated and all("{Time}" in l["url_template"] for l in dated)

async def test_layers_leak_no_secret(client):
    r = await client.get("/geoint/layers")
    body = r.text.lower()
    assert "api_key" not in body and "tomtom" not in body
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest backend/tests/test_geoint_layers.py -v` → FAIL (404 / no route).
- [ ] **Step 3: Implement `backend/app/api/geoint.py`** — router prefix `/geoint`; module-level `LAYERS: list[dict]` constant; `@router.get("/layers")` async, deps `get_current_operator`, returns `{"layers": LAYERS}`. Register in `main.py`. Use the existing `client` test fixture (authenticated) — follow `test_geo_providers.py` for the fixture.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit.**

---

### Task 2: Frontend — layer catalogue + basemap picker

**Files:**
- Create: `frontend/src/components/chat/geoint/layers.ts` (fetch + types), `frontend/src/components/chat/geoint/BasemapPicker.tsx`
- Modify: `frontend/src/components/chat/MapCard.tsx` (replace the Phase 0 three-chip `TILE_MODES` switcher with `BasemapPicker`), `frontend/src/pages/MapView.tsx` (use the same picker for its base layer)
- Verify: `pnpm typecheck` + `pnpm build`

**Interfaces:**
- Consumes: `GET /geoint/layers` via the `api.get` helper (`frontend/src/lib/api.ts`). Consumes Task 1's `LayerDef` shape.
- Produces: `layers.ts` exports `type LayerDef`, `fetchLayers(): Promise<LayerDef[]>`, and `DEFAULT_LAYERS: LayerDef[]` (a keyless fallback used if the fetch fails, so the map always has basemaps). `BasemapPicker` props: `{ layers: LayerDef[]; baseId: string; overlayIds: string[]; onBase(id): void; onToggleOverlay(id): void }`, rendering grouped chips (Reference / Imagery / Terrain) and keeping Dark as the default base.

- [ ] **Step 1: Write `layers.ts`** — types, `fetchLayers` (calls `api.get`, falls back to `DEFAULT_LAYERS` on error), `DEFAULT_LAYERS` mirroring Task 1's catalogue (OSM dark/standard, Esri imagery, hillshade).
- [ ] **Step 2: Write `BasemapPicker.tsx`** — grouped chip UI from the props above; base is single-select, overlays multi-toggle.
- [ ] **Step 3: Integrate into `MapCard`** — fetch layers on mount; render the active base `TileLayer` from `url_template` (dark base keeps the `.kai-dark-tiles` filter; satellite/hillshade do not); render overlay `TileLayer`s stacked with opacity; replace the Phase 0 chip switcher with `BasemapPicker`. Preserve all Phase 0 behaviour (fullscreen, follow, routing).
- [ ] **Step 4: Integrate into `MapView`** — same picker for its base layer, keeping its existing live `/geo/*` layers.
- [ ] **Step 5: Verify** — `pnpm typecheck` (expect exit 0) and `pnpm build` (expect success).
- [ ] **Step 6: Commit.**

---

### Task 3: Frontend — temporal before/after compare

**Files:**
- Create: `frontend/src/components/chat/geoint/DateCompare.tsx`
- Modify: `frontend/src/components/chat/MapCard.tsx` (mount `DateCompare` controls when the active base is `dated`)
- Verify: `pnpm typecheck` + `pnpm build`

**Interfaces:**
- Consumes: the active `LayerDef` (from Task 2). A dated layer's `url_template` has a `{Time}` token replaced with `YYYY-MM-DD`.
- Produces: `DateCompare` renders (a) a single date picker that re-templates the active dated layer's tiles, and (b) a **compare mode** rendering two stacked `TileLayer`s (date A under, date B over) with a draggable **swipe divider** (CSS clip on the top layer's pane) plus an **opacity-slider** secondary toggle that cross-fades A↔B. Compare mode is only offered when `layer.dated`. An empty-tiles date surfaces a "no imagery this date" hint and leaves the other layer visible (Review Focus item).

- [ ] **Step 1: Write `DateCompare.tsx`** — date state (single + A/B), mode toggle (single | swipe | opacity), swipe divider via draggable handle controlling a clip width, opacity via a slider on the top layer. `{Time}` → date substitution helper.
- [ ] **Step 2: Integrate into `MapCard`** — show the `DateCompare` control row only when the selected base `dated` is true; render its layers above the base tiles and below markers/routes.
- [ ] **Step 3: Verify** — `pnpm typecheck` + `pnpm build`.
- [ ] **Step 4: Manual check** — set a dated GIBS layer, pick two dates, drag the divider; pick a date with no pass → "no imagery this date" hint shows, the other layer stays. Switching basemap does not lose the chosen dates until compare is closed.
- [ ] **Step 5: Commit.**

---

### Task 4: Backend — `GET /geoint/elevation` proxy

**Files:**
- Modify: `backend/app/api/geoint.py` (add the route)
- Test: `backend/tests/test_geoint_elevation.py`

**Interfaces:**
- Consumes: Task 1's router.
- Produces: `GET /geoint/elevation?points=lat,lon|lat,lon|…` → on success `{"ok": true, "results": [{"lat": float, "lon": float, "elevation_m": float|None}]}`; malformed `points` → HTTP 422; upstream (OpenTopoData) failure → `{"ok": false, "reason": str}` with HTTP 200. Internally: parse ≤100 points, round coords for a simple in-process TTL cache, call OpenTopoData `srtm30m` via `httpx` (short timeout), map results back. Never raises to a 5xx.

- [ ] **Step 1: Write the failing test**

```python
# test_geoint_elevation.py — monkeypatch the httpx/OpenTopoData call
async def test_elevation_ok(client, monkeypatch):
    # patch the upstream call to return two elevations
    r = await client.get("/geoint/elevation", params={"points": "0,0|1,1"})
    assert r.status_code == 200
    body = r.json(); assert body["ok"] is True
    assert len(body["results"]) == 2 and "elevation_m" in body["results"][0]

async def test_elevation_malformed_points(client):
    r = await client.get("/geoint/elevation", params={"points": "not-a-coord"})
    assert r.status_code == 422

async def test_elevation_upstream_failure_is_handled(client, monkeypatch):
    # patch the upstream call to raise httpx.HTTPError
    r = await client.get("/geoint/elevation", params={"points": "0,0"})
    assert r.status_code == 200 and r.json()["ok"] is False
```

- [ ] **Step 2: Run tests, verify fail.**
- [ ] **Step 3: Implement the route** — a `_parse_points(s) -> list[tuple[float,float]]` raising `HTTPException(422)` on bad input; a module-level TTL cache dict; an `async` OpenTopoData fetch wrapped in `try/except (httpx.HTTPError, ValueError)` returning `{ok: False, reason}`. Factor the upstream call into a helper the test can monkeypatch.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit.**

---

### Task 5: Frontend — elevation profile + infrastructure datasets

**Files:**
- Create: `frontend/src/components/chat/geoint/ElevationProfile.tsx`
- Modify: `frontend/src/components/chat/MapCard.tsx` (point-elevation in marker popups; elevation profile along a drawn route; expanded Overpass categories)
- Verify: `pnpm typecheck` + `pnpm build`

**Interfaces:**
- Consumes: `GET /geoint/elevation` via `api.get`. The existing `findNearby`/Overpass pattern in `MapCard`.
- Produces: `ElevationProfile` takes sampled points `{lat,lon}[]`, calls `/geoint/elevation`, renders a compact sparkline with min/max/gain; hides itself on `{ok:false}`. `MapCard` gains an "infrastructure" chip group alongside "nearby" covering `power`, `bridge`, `aeroway`, `harbour`, `telecom`/`communication` towers, `pipeline` (same Overpass mechanism as the amenity chips, different tag filters).

- [ ] **Step 1: Write `ElevationProfile.tsx`** — sample N points along the active route polyline, fetch elevations, render sparkline; graceful hide on failure.
- [ ] **Step 2: Add point elevation to marker popups** — on popup open, fetch a single elevation and show `elevation_m` (or omit on failure).
- [ ] **Step 3: Add the infrastructure chip group** — reuse `findNearby`, parameterized by Overpass tag filters for the new categories.
- [ ] **Step 4: Verify** — `pnpm typecheck` + `pnpm build`.
- [ ] **Step 5: Commit.**

---

### Task 6: Backend — `POST /geoint/evidence` + investigation map features

**Files:**
- Modify: `backend/app/api/geoint.py` (add the route), `backend/app/api/maps.py` (extend `investigation_map` to emit saved geoint evidence as features)
- Test: `backend/tests/test_geoint_evidence.py`

**Interfaces:**
- Consumes: Task 1's router; the existing `Evidence` model + `EvidenceRepository` (`backend/app/database/repositories/graph_repos.py`) and `_get_investigation_or_404` pattern from `investigations.py`.
- Produces: `POST /geoint/evidence` body `{investigation_id: UUID, annotations: dict (GeoJSON FeatureCollection), layer_id: str, dates: list[str] (0–2), bounds: dict, note: str|None, provider_url: str (clean https), collected_at: datetime|None, entity_id: UUID|None}`. Behaviour: 404 if the investigation doesn't exist; 422 if `annotations` isn't a valid FeatureCollection (`type == "FeatureCollection"` and a `features` list) or `provider_url` isn't https — **before** any write. On success writes exactly one `Evidence` row: `type="geoint"`, `source_url=provider_url`, `collected_at = dates[-1] parsed or now()`, `raw_metadata = {annotations, layer_id, dates, bounds, note}`, returns the `EvidenceOut` shape (201). Also: `investigation_map` in `maps.py` additionally returns `features` — the GeoJSON from every `type="geoint"` evidence row of that investigation — alongside the existing `points`.

- [ ] **Step 1: Write the failing test**

```python
# test_geoint_evidence.py
async def test_evidence_written_once(client, an_investigation):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.0, -1.9]}, "properties": {}}]}
    r = await client.post("/geoint/evidence", json={
        "investigation_id": str(an_investigation.id), "annotations": fc,
        "layer_id": "gibs_modis_truecolor", "dates": ["2024-01-01"],
        "bounds": {"n":0,"s":-2,"e":31,"w":29}, "provider_url": "https://gibs.earthdata.nasa.gov/"})
    assert r.status_code == 201 and r.json()["type"] == "geoint"
    m = await client.get(f"/investigations/{an_investigation.id}/map")
    assert len(m.json()["features"]) == 1

async def test_evidence_bad_investigation_404(client):
    r = await client.post("/geoint/evidence", json={"investigation_id": str(uuid4()),
        "annotations": {"type":"FeatureCollection","features":[]},
        "layer_id":"x","dates":[],"bounds":{},"provider_url":"https://x/"})
    assert r.status_code == 404

async def test_evidence_bad_geojson_422_no_write(client, an_investigation):
    r = await client.post("/geoint/evidence", json={"investigation_id": str(an_investigation.id),
        "annotations": {"type":"NotAFC"}, "layer_id":"x","dates":[],"bounds":{},"provider_url":"https://x/"})
    assert r.status_code == 422
    m = await client.get(f"/investigations/{an_investigation.id}/map")
    assert m.json()["features"] == []
```

- [ ] **Step 2: Run tests, verify fail.** (Add an `an_investigation` fixture if none exists — follow `test_investigations_api.py`.)
- [ ] **Step 3: Implement** — Pydantic body with a `field_validator` on `annotations` (FeatureCollection shape) and `provider_url` (https); check investigation exists → 404; write the `Evidence` row via `EvidenceRepository(session).add(...)` + `session.flush()`; extend `investigation_map` to query `type="geoint"` evidence and append `features`.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit.**

---

### Task 7: Frontend — annotate layer + save to investigation

**Files:**
- Create: `frontend/src/components/chat/geoint/AnnotateLayer.tsx`
- Modify: `frontend/src/components/chat/MapCard.tsx` (mount annotate controls; "Save to investigation"; render saved `features`), `frontend/src/pages/MapView.tsx` (render saved `features` from `/investigations/{id}/map`)
- Verify: `pnpm typecheck` + `pnpm build`

**Interfaces:**
- Consumes: `POST /geoint/evidence` and the extended `investigation_map` `features` (Task 6); the investigations list API for the case picker; the active `layer_id`/dates/bounds from Tasks 2–3.
- Produces: `AnnotateLayer` — add **pin**, **polygon**, **line/measure**, each with an optional note; an annotation list with delete; it builds a GeoJSON FeatureCollection. A "Save to investigation" action picks an open case and POSTs `{investigation_id, annotations, layer_id, dates, bounds, provider_url}`. Leaflet draw handlers are registered on enter and **removed on unmount and on fullscreen toggle** (Review Focus). Saved `features` render as read-only geometry on both map surfaces.

- [ ] **Step 1: Write `AnnotateLayer.tsx`** — minimal in-house draw (map click to add pin/vertex; finish polygon/line), note field, list + delete, FeatureCollection builder. Register map handlers in an effect with a cleanup that removes them.
- [ ] **Step 2: Add "Save to investigation"** — case picker (reuse investigations API) → POST to `/geoint/evidence` with the active layer/date/bounds; inline success/error (accent colour), matching existing patterns.
- [ ] **Step 3: Render saved features** — fetch `features` from `investigation_map`; draw as read-only polygons/lines/pins in `MapCard` (when a case is in context) and `MapView`.
- [ ] **Step 4: Verify** — `pnpm typecheck` + `pnpm build`.
- [ ] **Step 5: Manual check** — draw a polygon, save to a case; it reappears on that investigation's map. Toggle fullscreen and unmount — no leaked Leaflet handlers (no duplicate clicks after re-mount). Switching basemap keeps the active annotations.
- [ ] **Step 6: Commit.**
