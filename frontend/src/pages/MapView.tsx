import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MapContainer, TileLayer, CircleMarker, Popup, useMapEvents } from "react-leaflet";
import type { Map as LeafletMap } from "leaflet";
import { Map as MapIcon, Plane, Ship, Flame, Video, RefreshCw } from "lucide-react";
import "leaflet/dist/leaflet.css";

import { api } from "@/lib/api";
import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

interface GeoPoint { lat: number; lon: number; label: string; kind: string; meta?: any }
interface MapPoint { entity_id: string; type: string; label: string; lat: number; lon: number }

const KIND_COLOR: Record<string, string> = {
  aircraft: "#4593e5",
  vessel: "#30a46c",
  satellite_fire: "#e5484d",
  cctv: "#f5a623",
  entity: "#a855f7",
};
const LAYERS = [
  { key: "aircraft", label: "Aircraft", icon: Plane, path: "/geo/aircraft" },
  { key: "vessels", label: "Vessels", icon: Ship, path: "/geo/vessels" },
  { key: "fires", label: "Satellite fires", icon: Flame, path: "/geo/fires" },
  { key: "cctv", label: "Webcams/CCTV", icon: Video, path: "/geo/webcams" },
] as const;

function BoundsWatcher({ onBounds }: { onBounds: (b: any) => void }) {
  const map = useMapEvents({ moveend: () => onBounds(map.getBounds()) });
  useEffect(() => { onBounds(map.getBounds()); }, []); // eslint-disable-line
  return null;
}

export function MapView() {
  const [params, setParams] = useSearchParams();
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [selected, setSelected] = useState(params.get("investigation") ?? "");
  const [casePoints, setCasePoints] = useState<MapPoint[]>([]);
  const [cfg, setCfg] = useState<{ tomtom_key: string | null; layers: Record<string, boolean> } | null>(null);
  const [active, setActive] = useState<Record<string, boolean>>({});
  const [livePoints, setLivePoints] = useState<Record<string, GeoPoint[]>>({});
  const [loading, setLoading] = useState<string | null>(null);
  const boundsRef = useRef<any>(null);
  const mapRef = useRef<LeafletMap | null>(null);

  useEffect(() => {
    investigationsApi.list().then(setCases).catch(() => setCases([]));
    api.get<any>("/geo/config").then(setCfg).catch(() => setCfg(null));
  }, []);

  useEffect(() => {
    if (!selected) return setCasePoints([]);
    api.get<{ points: MapPoint[] }>(`/investigations/${selected}/map`).then((r) => setCasePoints(r.points)).catch(() => setCasePoints([]));
  }, [selected]);

  async function loadLayer(key: string) {
    const layer = LAYERS.find((l) => l.key === key)!;
    const b = boundsRef.current;
    let url = layer.path;
    if (key === "aircraft" || key === "vessels") {
      if (!b) return;
      url += `?lat_min=${b.getSouth().toFixed(3)}&lon_min=${b.getWest().toFixed(3)}&lat_max=${b.getNorth().toFixed(3)}&lon_max=${b.getEast().toFixed(3)}`;
    } else if (key === "fires" && b) {
      url += `?area=${b.getWest().toFixed(2)},${b.getSouth().toFixed(2)},${b.getEast().toFixed(2)},${b.getNorth().toFixed(2)}&day_range=2`;
    }
    setLoading(key);
    try {
      const r = await api.get<{ available: boolean; points: GeoPoint[]; detail?: string }>(url);
      setLivePoints((p) => ({ ...p, [key]: r.available ? r.points : [] }));
      if (!r.available) alert(`${layer.label}: ${r.detail ?? "unavailable"}`);
    } catch {
      setLivePoints((p) => ({ ...p, [key]: [] }));
    } finally {
      setLoading(null);
    }
  }

  async function toggleLayer(key: string) {
    const on = !active[key];
    setActive((a) => ({ ...a, [key]: on }));
    if (on) await loadLayer(key);
    else setLivePoints((p) => ({ ...p, [key]: [] }));
  }

  const center = useMemo<[number, number]>(() => (casePoints.length ? [casePoints[0].lat, casePoints[0].lon] : [-1.95, 30.06]), [casePoints]);
  const tomtom = cfg?.tomtom_key;

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <MapIcon size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Geographic Intelligence</h1>
        <select
          value={selected}
          onChange={(e) => { setSelected(e.target.value); setParams(e.target.value ? { investigation: e.target.value } : {}); }}
          className="ml-auto rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
        >
          <option value="">Case layer: none…</option>
          {cases.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
        </select>
      </div>

      {/* live layer toggles */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {LAYERS.map((l) => {
          const Icon = l.icon;
          const avail = cfg?.layers?.[l.key === "fires" ? "satellite_fires" : l.key === "cctv" ? "cctv" : l.key];
          const on = active[l.key];
          return (
            <button
              key={l.key}
              onClick={() => toggleLayer(l.key)}
              disabled={!avail}
              title={avail ? "" : "Not configured (add API key)"}
              className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs disabled:opacity-40"
              style={{ borderColor: on ? KIND_COLOR[l.key === "fires" ? "satellite_fire" : l.key === "cctv" ? "cctv" : l.key] : "var(--kai-border)", color: on ? "var(--kai-ink)" : "var(--kai-muted)" }}
            >
              <Icon size={13} /> {l.label}
              {loading === l.key && " …"}
              {on && livePoints[l.key] && ` (${livePoints[l.key].length})`}
            </button>
          );
        })}
        {Object.values(active).some(Boolean) && (
          <button onClick={() => LAYERS.forEach((l) => active[l.key] && loadLayer(l.key))} className="flex items-center gap-1 kai-metadata hover:text-ink">
            <RefreshCw size={12} /> reload in view
          </button>
        )}
      </div>

      <div className="overflow-hidden rounded-lg border border-line" style={{ height: 520 }}>
        <MapContainer center={center} zoom={casePoints.length ? 6 : 3} style={{ height: "100%", width: "100%", background: "#0e131d" }} ref={mapRef as any}>
          {tomtom ? (
            <TileLayer attribution="&copy; TomTom" url={`https://{s}.api.tomtom.com/map/1/tile/basic/night/{z}/{x}/{y}.png?key=${tomtom}`} subdomains={["a", "b", "c", "d"]} />
          ) : (
            <TileLayer attribution="&copy; OpenStreetMap, CARTO" url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" />
          )}
          <BoundsWatcher onBounds={(b) => (boundsRef.current = b)} />

          {casePoints.map((p) => (
            <CircleMarker key={p.entity_id} center={[p.lat, p.lon]} radius={7} pathOptions={{ color: KIND_COLOR.entity, fillColor: KIND_COLOR.entity, fillOpacity: 0.7 }}>
              <Popup><div style={{ fontSize: 12 }}><strong>{p.label}</strong><br />{p.type}</div></Popup>
            </CircleMarker>
          ))}

          {LAYERS.map((l) => (active[l.key] ? (livePoints[l.key] ?? []).map((p, i) => {
            const color = KIND_COLOR[p.kind] ?? "#8b93a7";
            return (
              <CircleMarker key={`${l.key}-${i}`} center={[p.lat, p.lon]} radius={5} pathOptions={{ color, fillColor: color, fillOpacity: 0.6 }}>
                <Popup><div style={{ fontSize: 12 }}><strong>{p.label}</strong><br />{p.kind}{p.meta?.detail_url ? <><br /><a href={p.meta.detail_url} target="_blank" rel="noreferrer">view</a></> : null}</div></Popup>
              </CircleMarker>
            );
          }) : null))}
        </MapContainer>
      </div>
      <div className="kai-metadata mt-2">
        {tomtom ? "TomTom night tiles" : "CARTO dark tiles"} · pan/zoom then toggle a live layer to load it for the current view.
      </div>
    </div>
  );
}
