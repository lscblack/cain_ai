import { useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline, useMap } from "react-leaflet";
import {
  MapPin, Navigation, Navigation2, Crosshair, ExternalLink, Loader2, LocateFixed,
  Maximize2, Minimize2,
} from "lucide-react";
import "leaflet/dist/leaflet.css";
import { BasemapPicker } from "@/components/chat/geoint/BasemapPicker";
import { DEFAULT_LAYERS, fetchLayers, layerUrl, type LayerDef } from "@/components/chat/geoint/layers";
import { haversineKm, type Amenity, type GeoPoint } from "@/components/chat/util";

// Public, keyless services. Both calls degrade gracefully: on any failure the
// card still shows the point(s), and routing falls back to an OSM link.
const OVERPASS = "https://overpass-api.de/api/interpreter";
const OSRM = "https://router.project-osrm.org/route/v1/driving";

// Child inside the MapContainer: reacts to fullscreen (Leaflet must re-measure
// or tiles render gray) and to live "follow" updates (recenter on the operator).
function MapController({ fullscreen, follow, me }: {
  fullscreen: boolean; follow: boolean; me: GeoPoint | null;
}) {
  const map = useMap();
  useEffect(() => {
    const t = setTimeout(() => map.invalidateSize(), 220);
    return () => clearTimeout(t);
  }, [fullscreen, map]);
  useEffect(() => {
    if (follow && me) map.setView([me.lat, me.lon], Math.max(map.getZoom(), 15), { animate: true });
  }, [follow, me, map]);
  return null;
}

const NEARBY: Amenity[] = [
  { amenity: "hospital", label: "Hospitals" },
  { amenity: "police", label: "Police" },
  { amenity: "fuel", label: "Fuel" },
  { amenity: "pharmacy", label: "Pharmacy" },
  { amenity: "bank", label: "ATM/Bank" },
  { amenity: "restaurant", label: "Food" },
];

function center(points: GeoPoint[]): [number, number] {
  const n = points.length || 1;
  const lat = points.reduce((s, p) => s + p.lat, 0) / n;
  const lon = points.reduce((s, p) => s + p.lon, 0) / n;
  return [lat || 0, lon || 0];
}

function dirUrl(to: GeoPoint, from?: GeoPoint | null): string {
  const t = `${to.lat},${to.lon}`;
  return from
    ? `https://www.openstreetmap.org/directions?from=${from.lat},${from.lon}&to=${t}`
    : `https://www.openstreetmap.org/directions?to=${t}`;
}

export function MapCard({
  points, autoAmenity, autoLocate, query,
}: {
  points: GeoPoint[];
  autoAmenity?: Amenity;
  autoLocate?: boolean;
  query?: string;
}) {
  const [me, setMe] = useState<GeoPoint | null>(null);
  const [nearby, setNearby] = useState<GeoPoint[]>([]);
  const [nearbyKind, setNearbyKind] = useState<string | null>(null);
  const [route, setRoute] = useState<[number, number][] | null>(null);
  const [routeInfo, setRouteInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [layers, setLayers] = useState<LayerDef[]>(DEFAULT_LAYERS);
  const [baseId, setBaseId] = useState("osm_dark");
  const [overlayIds, setOverlayIds] = useState<string[]>([]);
  const [fullscreen, setFullscreen] = useState(false);
  const [following, setFollowing] = useState(false);
  const started = useRef(false);

  useEffect(() => { fetchLayers().then(setLayers); }, []);
  const baseLayer = layers.find((l) => l.id === baseId && l.kind === "base") ?? layers.find((l) => l.kind === "base");
  const overlays = layers.filter((l) => l.kind === "overlay" && overlayIds.includes(l.id));
  const toggleOverlay = (id: string) => setOverlayIds((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id]));

  const origin: GeoPoint | null = points[0] ?? me;

  // Live "follow": track the operator and feed `me`; cleanup stops the watcher
  // on toggle-off and on unmount, so no geolocation watcher ever leaks.
  useEffect(() => {
    if (!following) return;
    if (!navigator.geolocation) { setErr("This device has no location service."); setFollowing(false); return; }
    const id = navigator.geolocation.watchPosition(
      (pos) => setMe({ lat: pos.coords.latitude, lon: pos.coords.longitude, label: "Your location", kind: "me" }),
      () => { setErr("Location permission denied — can't follow."); setFollowing(false); },
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 10000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [following]);

  // Esc exits fullscreen.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  async function findNearby(o: GeoPoint, amenity: string, label: string) {
    setBusy(`nearby:${amenity}`); setErr(null);
    try {
      const q = `[out:json][timeout:20];(node["amenity"="${amenity}"](around:5000,${o.lat},${o.lon});way["amenity"="${amenity}"](around:5000,${o.lat},${o.lon}););out center 40;`;
      const resp = await fetch(OVERPASS, { method: "POST", body: q });
      const data = await resp.json();
      const pts: GeoPoint[] = (data.elements || [])
        .map((e: any) => {
          const lat = e.lat ?? e.center?.lat, lon = e.lon ?? e.center?.lon;
          if (typeof lat !== "number" || typeof lon !== "number") return null;
          return { lat, lon, label: e.tags?.name || label, kind: amenity, distKm: haversineKm(o, { lat, lon }) };
        })
        .filter(Boolean) as GeoPoint[];
      pts.sort((a, b) => (a.distKm ?? 0) - (b.distKm ?? 0));
      setNearby(pts); setNearbyKind(label);
      if (pts.length === 0) setErr(`No ${label.toLowerCase()} found within 5 km.`);
    } catch { setErr("Nearby lookup failed (Overpass unreachable)."); }
    finally { setBusy(null); }
  }

  function locateMe(then?: (p: GeoPoint) => void) {
    if (!navigator.geolocation) { setErr("This device has no location service."); return; }
    setLocating(true); setErr(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const p: GeoPoint = { lat: pos.coords.latitude, lon: pos.coords.longitude, label: "Your location", kind: "me" };
        setMe(p); setLocating(false); then?.(p);
      },
      () => { setLocating(false); setErr("Location permission denied — can't resolve 'near me'."); },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  // Auto flow: for a "near me" query, locate then search; for a resolved place
  // with a requested amenity, search around that place.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (points.length === 0 && autoLocate) {
      locateMe((p) => { if (autoAmenity) findNearby(p, autoAmenity.amenity, autoAmenity.label); });
    } else if (points.length > 0 && autoAmenity) {
      findNearby(points[0], autoAmenity.amenity, autoAmenity.label);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function routeTo(dest: GeoPoint) {
    setBusy("route"); setErr(null);
    const go = (from: GeoPoint) => fetch(`${OSRM}/${from.lon},${from.lat};${dest.lon},${dest.lat}?overview=full&geometries=geojson`)
      .then((r) => r.json())
      .then((data) => {
        const r = data.routes?.[0];
        if (!r) throw new Error("no route");
        setRoute(r.geometry.coordinates.map((p: [number, number]) => [p[1], p[0]]));
        setRouteInfo(`${(r.distance / 1000).toFixed(1)} km · ~${Math.round(r.duration / 60)} min by car`);
      })
      .catch(() => window.open(dirUrl(dest, from), "_blank", "noopener,noreferrer"))
      .finally(() => setBusy(null));
    if (me) return go(me);
    locateMe((p) => go(p));
  }

  const all = [...points, ...nearby, ...(me ? [me] : [])];
  const bounds = all.length ? center(all) : [0, 0] as [number, number];
  const searched = query || points[0]?.label;

  if (!origin && !locating) {
    return (
      <div className="mt-2 rounded-md border p-3 text-xs" style={{ borderColor: "#262b36", background: "#0b0e14" }}>
        <div className="mb-2 text-muted">{searched ? `“${searched}” needs your location.` : "This needs your location."}</div>
        <button onClick={() => locateMe((p) => { if (autoAmenity) findNearby(p, autoAmenity.amenity, autoAmenity.label); })}
          className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel" style={{ color: "var(--kai-hud)" }}>
          <LocateFixed size={12} /> Use my location
        </button>
        {err && <div className="mt-2" style={{ color: "var(--kai-accent)" }}>{err}</div>}
      </div>
    );
  }
  if (!origin) {
    return (
      <div className="mt-2 flex items-center gap-2 rounded-md border p-3 text-xs" style={{ borderColor: "#262b36", background: "#0b0e14", color: "var(--kai-muted)" }}>
        <Loader2 size={12} className="kai-spin" /> getting your location…
      </div>
    );
  }

  return (
    <div
      className={fullscreen ? "fixed inset-0 z-[1200] flex flex-col" : "mt-2 overflow-hidden rounded-md border"}
      style={{ borderColor: "#262b36", background: "#0b0e14" }}>
      <div className="flex flex-wrap items-center gap-1.5 border-b px-2 py-1" style={{ borderColor: "#1a1e27", background: "#11151d" }}>
        <MapPin size={11} style={{ color: "var(--kai-hud)" }} />
        <span className="font-mono text-[10px]" style={{ color: "#6b7280" }}>
          {searched ? `${searched} · ` : ""}{nearbyKind ? `${nearby.length} ${nearbyKind.toLowerCase()}` : `${origin.lat.toFixed(4)}, ${origin.lon.toFixed(4)}`}
          {me && origin.kind === "me" ? " · from your location" : ""}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <BasemapPicker layers={layers} baseId={baseId} overlayIds={overlayIds}
            onBase={setBaseId} onToggleOverlay={toggleOverlay} />
          {route && (
            <button onClick={() => setFollowing((v) => !v)} title="Follow the route with your live location"
              className="flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] hover:bg-panel"
              style={{ borderColor: following ? "var(--kai-hud-dim)" : "var(--kai-border)", color: following ? "var(--kai-hud)" : "var(--kai-muted)" }}>
              <Navigation2 size={10} /> {following ? "Following…" : "Follow"}
            </button>
          )}
          {points.length > 0 && (
            <button onClick={() => routeTo(points[0])} disabled={busy === "route"}
              className="flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[10px] hover:bg-panel disabled:opacity-40"
              style={{ color: "var(--kai-hud)" }} title="Driving route from your location">
              {busy === "route" ? <Loader2 size={10} className="kai-spin" /> : <Navigation size={10} />} Route from me
            </button>
          )}
          <button onClick={() => setFullscreen((v) => !v)} title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
            className="rounded border border-line px-1.5 py-0.5 text-[10px] text-muted hover:bg-panel">
            {fullscreen ? <Minimize2 size={10} /> : <Maximize2 size={10} />}
          </button>
          <a href={dirUrl(origin, me)} target="_blank" rel="noopener noreferrer"
            className="rounded border border-line px-1.5 py-0.5 text-[10px] text-muted hover:bg-panel" title="Open in OpenStreetMap">
            <ExternalLink size={10} />
          </a>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1 px-2 py-1" style={{ background: "#0e131d" }}>
        <Crosshair size={10} className="text-muted" />
        <span className="kai-metadata mr-1">nearby:</span>
        {NEARBY.map((n) => (
          <button key={n.amenity} onClick={() => origin && findNearby(origin, n.amenity, n.label)} disabled={!!busy || !origin}
            className="rounded border px-1.5 py-0.5 text-[10px] hover:bg-panel disabled:opacity-40"
            style={{ borderColor: nearbyKind === n.label ? "var(--kai-hud-dim)" : "var(--kai-border)", color: nearbyKind === n.label ? "var(--kai-hud)" : "var(--kai-muted)" }}>
            {busy === `nearby:${n.amenity}` ? "…" : n.label}
          </button>
        ))}
      </div>

      {(routeInfo || err) && (
        <div className="px-2 py-1 text-[10px]" style={{ color: err ? "var(--kai-accent)" : "var(--kai-verified)" }}>
          {err || routeInfo}
        </div>
      )}

      {/* Keyless OpenStreetMap tiles, darkened with a CSS filter so no API key
          is needed (Carto/Stadia now require one). The filter only touches the
          tile images; vector markers/routes keep their colours. */}
      <style>{`.kai-dark-tiles{filter:invert(1) hue-rotate(180deg) brightness(0.92) contrast(0.9) saturate(0.85);}`}</style>
      <div style={fullscreen ? { flex: 1, minHeight: 0 } : { height: 260 }}>
        <MapContainer center={bounds} zoom={nearby.length ? 13 : (points.length > 1 ? 11 : 13)} style={{ height: "100%", width: "100%", background: "#0b0e14" }} scrollWheelZoom={fullscreen}>
          <MapController fullscreen={fullscreen} follow={following} me={me} />
          {baseLayer && (
            <TileLayer key={baseLayer.id} attribution={baseLayer.attribution}
              className={baseLayer.id === "osm_dark" ? "kai-dark-tiles" : undefined}
              url={layerUrl(baseLayer)} maxNativeZoom={baseLayer.max_zoom} maxZoom={19} />
          )}
          {overlays.map((o) => (
            <TileLayer key={o.id} attribution={o.attribution} url={layerUrl(o)} maxNativeZoom={o.max_zoom} maxZoom={19} opacity={0.6} />
          ))}
          {me && (
            <CircleMarker center={[me.lat, me.lon]} radius={7} pathOptions={{ color: "#22d3ee", fillColor: "#22d3ee", fillOpacity: 0.9 }}>
              <Popup>Your location</Popup>
            </CircleMarker>
          )}
          {points.map((p, i) => (
            <CircleMarker key={`p${i}`} center={[p.lat, p.lon]} radius={7} pathOptions={{ color: "#22d3ee", fillColor: "#22d3ee", fillOpacity: 0.7 }}>
              <Popup>{p.label || `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`}</Popup>
            </CircleMarker>
          ))}
          {nearby.map((p, i) => (
            <CircleMarker key={`n${i}`} center={[p.lat, p.lon]} radius={5} pathOptions={{ color: "#f5a623", fillColor: "#f5a623", fillOpacity: 0.7 }}>
              <Popup>
                <div className="font-semibold">{p.label}</div>
                {p.distKm != null && <div>{p.distKm.toFixed(2)} km away</div>}
                <a href={dirUrl(p, me)} target="_blank" rel="noopener noreferrer">Directions →</a>
              </Popup>
            </CircleMarker>
          ))}
          {route && <Polyline positions={route} pathOptions={{ color: "#30a46c", weight: 4, opacity: 0.8 }} />}
        </MapContainer>
      </div>

      {nearby.length > 0 && (
        <div className="max-h-40 overflow-auto border-t px-2 py-1" style={{ borderColor: "#1a1e27" }}>
          {nearby.slice(0, 20).map((p, i) => (
            <div key={i} className="flex items-center gap-2 py-0.5 text-[11px]">
              <span className="w-6 text-right text-muted">{i + 1}.</span>
              <span className="flex-1 truncate">{p.label}</span>
              {p.distKm != null && <span className="hud-mono" style={{ color: "var(--kai-hud)" }}>{p.distKm.toFixed(2)} km</span>}
              <a href={dirUrl(p, me)} target="_blank" rel="noopener noreferrer" className="text-muted hover:text-ink" title="Directions">
                <Navigation size={11} />
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
