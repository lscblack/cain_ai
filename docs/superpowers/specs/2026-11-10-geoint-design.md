# KAI Geospatial Intelligence (GEOINT) — Design

Sub-project (follow-on to the chat map foundation shipped as *GEOINT Phase 0*:
tile modes, fullscreen, follow-route). This spec covers the remaining phases of
a keyless-first GEOINT capability: analysis-grade imagery, change-over-time,
terrain and infrastructure datasets, and evidence-linked investigation maps.

## Problem

KAI's operator needs to reason about places, not just plot them. Today the map
plots points, finds nearby amenities, and draws driving routes. GEOINT adds the
analyst layer: look at satellite imagery, **compare the same place across
dates** to spot visible change (new construction, clearing, flooding, vehicle
build-up), read terrain and public infrastructure, and **capture what they see
as provenanced evidence on an investigation case**.

The constraint set by the operator: **keyless-only providers** — no new API
keys. This bounds resolution and imagery cadence (see Risks) but makes the whole
capability work on a fresh install with zero setup.

## Goals

- Dated satellite imagery the operator can step through in time, with a
  **before/after compare** control.
- A **high-resolution (undated) imagery** base for detail, plus terrain
  (elevation + hillshade) and expanded public-infrastructure datasets.
- **Annotations** (pins, polygons, measurements) the operator can draw on the
  map and **save to an investigation as Evidence**, carrying the imagery
  date/layer and view bounds as provenance.
- Everything degrades gracefully: any provider failure leaves the map usable.

## Non-goals

- No paid imagery (Planet/Maxar/Sentinel Hub paid). No new API keys in any
  phase of this spec.
- No fully-automated computer-vision change detection in v1. "Identify visible
  changes" is **human-in-the-loop**: the tooling makes change easy to *see* and
  *record*; it does not classify change by itself. An assisted tile-diff is
  scoped as optional Phase 5 and explicitly gated on imagery quality.
- No 3D globe / Cesium view (the `cesium_ion_token` path stays as-is in MapView).
- No changes to Phase 0 behaviour (tile modes / fullscreen / follow-route).

## Providers (all keyless)

| Use | Provider | Notes |
| --- | --- | --- |
| Dated imagery (temporal) | **NASA GIBS** WMTS | Global, daily, keyless. MODIS/VIIRS ~250 m; some layers finer. Date-templated tile URLs. |
| High-res base imagery | **Esri World Imagery** | Keyless, high-res, **undated** (single mosaic). Already used in Phase 0 "Satellite". |
| Streets / reference | **OpenStreetMap** | Keyless. Phase 0. |
| Point elevation + profile | **OpenTopoData** (public API) | Keyless, rate-limited; SRTM 30 m. Server-proxied + cached. |
| Hillshade / terrain tiles | **ESRI World Hillshade** (or OpenTopoMap) | Keyless tile overlay. |
| Infrastructure datasets | **Overpass** | Keyless. Phase 0 nearby, expanded here. |
| Routing | **OSRM** demo | Keyless. Phase 0. |

The backend never stores a provider secret for these; GIBS/Esri/OSM/hillshade
are browser-fetched tiles, OpenTopoData is proxied server-side only to add
caching and keep the operator's coordinates off a third party where avoidable.

## Architecture

Frontend: the chat `MapCard` and the full-page `MapView` share a new
`geoint/` module (tile-layer catalogue, a date/compare control, a draw/annotate
layer). Backend: a small `geoint` API surface for the imagery-layer catalogue,
an elevation proxy, and saving annotations as `Evidence`. Imagery tiles are
fetched directly by the browser (no server egress); only elevation and evidence
touch the backend.

Data flow for a compare: operator picks layer + two dates → the map renders two
GIBS tile layers (A under, B over) with a swipe divider → operator draws a
polygon over a visible change → "Save to investigation" POSTs the geometry +
both dates + layer + view bounds → backend writes one `Evidence` row
(`type="geoint"`, `source_url` = the GIBS layer URL for date B, `collected_at`
= date B).

---

## Phase 1 — GEOINT imagery base

**Goal:** a reusable keyless tile-layer catalogue, surfaced as an extended
basemap/overlay picker in both the chat card and the full map.

- **Backend** `GET /geoint/layers`: returns the keyless layer catalogue —
  `[{id, kind: "base"|"overlay", label, url_template, attribution, dated: bool,
  max_zoom}]`. Static config (no secret), but server-owned so the frontend
  layer list is one source of truth. Includes: `esri_imagery` (base, undated),
  `gibs_<layer>` (base, dated), `esri_hillshade` (overlay), `osm` /
  `osm_dark` (base).
- **Frontend** `geoint/layers.ts`: fetches the catalogue; `geoint/BasemapPicker`
  replaces the Phase 0 three-chip switcher with a grouped picker (Reference /
  Imagery / Terrain), still defaulting to Dark and still keyless-degrading.
- Overlays (hillshade) stack above a base via Leaflet `TileLayer` opacity.

**Deliverable:** operator can switch among OSM/Esri/GIBS bases and toggle a
hillshade overlay, in both map surfaces.

## Phase 2 — Temporal compare (before/after)

**Goal:** step a dated imagery layer through time and compare two dates.

- **Frontend** `geoint/DateCompare`:
  - A date picker bound to the active *dated* layer (GIBS); changing the date
    re-templates the tile URL (`{Time}` → `YYYY-MM-DD`).
  - A **compare mode**: two dates A/B rendered as stacked GIBS layers with a
    **swipe divider** (primary) the operator drags; an **opacity slider**
    (secondary toggle) cross-fades A↔B for slow changes. Decision: swipe is the
    default because it reads best for sharp spatial change; opacity is one click
    away for gradual change.
  - Compare mode is only offered when the active base is `dated: true`.
- No backend. GIBS tiles are browser-fetched. A missing tile for a date (no
  pass that day) shows a "no imagery this date" hint and leaves the other layer.

**Deliverable:** operator picks a GIBS layer, sets two dates, drags the divider,
and sees the same place then-vs-now.

## Phase 3 — Terrain & infrastructure datasets

**Goal:** read elevation and expanded public infrastructure.

- **Backend** `GET /geoint/elevation?points=lat,lon|lat,lon|…`: proxies
  OpenTopoData (SRTM), cached (lat/lon rounded key, TTL). Returns
  `[{lat, lon, elevation_m}]`. Rate-limit-aware; on upstream failure returns
  `{ok: false, reason}` and the UI hides the profile rather than erroring.
- **Frontend**:
  - Elevation profile: sample N points along a drawn route/line → call
    `/geoint/elevation` → render a small sparkline (min/max/gain).
  - Point elevation in a marker popup.
  - Expanded Overpass categories beyond Phase 0's amenities: `power`,
    `bridge`, `aeroway` (airports/runways), `harbour`/`port`,
    `telecom`/`communication_tower`, `pipeline`, `military` (where tagged).
    Grouped "infrastructure" chips alongside the existing "nearby" chips.

**Deliverable:** elevation profile along a route, point elevation, and an
infrastructure overlay for a place.

## Phase 4 — Annotations → Evidence

**Goal:** draw on the map and save it to an investigation with provenance.

- **Frontend** `geoint/AnnotateLayer` (leaflet draw-style, minimal in-house, no
  heavy plugin): add **pin**, **polygon/area**, **line/measurement**; each gets
  an optional note. An annotation panel lists them with delete.
- **"Save to investigation"**: pick an open case (reuses the investigations
  list) → POST the annotation set.
- **Backend** `POST /geoint/evidence`:
  `{investigation_id, annotations: GeoJSON FeatureCollection, layer_id,
  dates: [A?, B?], bounds, note}` → writes **one `Evidence` row**:
  - `type = "geoint"`
  - `source_url` = the active layer's templated URL (date B if comparing) —
    satisfies the model's required provenance.
  - `collected_at` = date B (dated layer) or `now()` (undated).
  - `raw_metadata` = `{annotations, layer_id, dates, bounds}`.
  - `processed_metadata` = `{summary, counts}`.
  - optional `entity_id` when the operator pins to an existing entity.
  No new table — the existing `Evidence` model carries it.
- The investigation map (`/investigations/{id}/map`) renders saved `geoint`
  evidence as its stored geometry.

**Deliverable:** operator draws a polygon over a change, saves it to a case,
and it reappears on that investigation's map with its imagery date as provenance.

## Phase 5 — Assisted change detection (optional, gated)

**Goal:** help the eye find change; never auto-conclude.

- A client-side **tile-diff**: for the current viewport and two GIBS dates,
  sample the rendered tiles to a canvas, compute per-pixel luminance delta, and
  shade regions above a threshold as a heat overlay the operator can toggle.
- Explicitly labelled "assist, not detection": output is a visual hint the
  operator still judges and annotates (Phase 4).
- **Gate:** only enabled for layers whose resolution makes a diff meaningful;
  with keyless ~250 m imagery this is coarse, so Phase 5 ships behind a flag and
  may be deferred until/unless a finer imagery source is added. This phase is
  the first candidate to cut if effort is constrained.

---

## Testing

- `GET /geoint/layers`: returns the catalogue; every entry has a non-empty
  `url_template` and `attribution`; no secret appears in the payload.
- `GET /geoint/elevation`: valid points → elevations; malformed `points` →
  422; upstream failure (mocked) → `{ok: false}`, never a 500.
- `POST /geoint/evidence`: writes exactly one `Evidence` row with `type`
  `"geoint"`, a non-empty `source_url`, `collected_at` set, and the GeoJSON in
  `raw_metadata`; a bad `investigation_id` → 404; a malformed FeatureCollection
  → 422 and nothing is written.
- Frontend: `tsc --noEmit` + `vite build` (repo has no component test harness).
  Manual: compare divider renders two dated layers; hillshade overlay toggles;
  annotations persist to a case and reload on its map.

## Risks / Anomalies (flagged)

1. **Keyless imagery is coarse / undated-or-low-cadence.** Esri is high-res but
   a single undated mosaic; GIBS is dated but ~250 m. True "spot the new
   building" change detection wants 10 m+ dated imagery (Sentinel-2), which
   needs a free Copernicus key. v1 is honest about this: temporal compare works,
   but fine change may be below the imagery's resolution. The provider table is
   a one-line swap if a key is added later.
2. **Public-endpoint courtesy limits.** Esri/GIBS/OpenTopoData/OSRM/Overpass
   demo servers are shared, rate-limited, and not SLA-backed. The elevation
   proxy caches; all map layers degrade gracefully. Heavy use may throttle.
3. **Phase 5 may not earn its keep** on keyless imagery — it is deliberately
   last, flagged, and cuttable.
4. **Evidence storage growth** if snapshots (images) are stored. v1 stores
   *geometry + metadata*, not rendered imagery bytes, keeping rows small; a
   PNG snapshot option is a later addition, not v1.
5. **Imagery ToS.** Esri/NASA imagery is used with attribution for internal
   analysis; redistribution of tiles is out of scope.

## Review Focus

- A GIBS date with no satellite pass returns empty tiles — the compare control
  must show "no imagery this date" and keep the other layer, not blank the map.
- `/geoint/elevation` must never 500 on upstream failure or a malformed point
  list; it returns a handled `{ok:false}`/422 and the profile hides.
- `/geoint/evidence` must reject a FeatureCollection that isn't valid GeoJSON
  and a non-existent `investigation_id` **before** writing, so no partial or
  orphan evidence row is created.
- The draw layer must clean up its Leaflet handlers on unmount / fullscreen
  toggle (same class of bug as the Phase 0 watcher) — no leaked map handlers.
- Switching basemaps must not drop an active annotation layer or compare state.
