import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { Map as MapIcon } from "lucide-react";
import "leaflet/dist/leaflet.css";

import { api } from "@/lib/api";
import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

interface MapPoint {
  entity_id: string;
  type: string;
  label: string;
  lat: number;
  lon: number;
}

export function MapView() {
  const [params, setParams] = useSearchParams();
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [selected, setSelected] = useState(params.get("investigation") ?? "");
  const [points, setPoints] = useState<MapPoint[]>([]);

  useEffect(() => {
    investigationsApi.list().then(setCases).catch(() => setCases([]));
  }, []);

  useEffect(() => {
    if (!selected) return setPoints([]);
    api.get<{ points: MapPoint[] }>(`/investigations/${selected}/map`)
      .then((r) => setPoints(r.points))
      .catch(() => setPoints([]));
  }, [selected]);

  const center = useMemo<[number, number]>(() => {
    if (points.length) return [points[0].lat, points[0].lon];
    return [10, 10];
  }, [points]);

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <MapIcon size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Geographic Intelligence</h1>
        <select
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setParams(e.target.value ? { investigation: e.target.value } : {});
          }}
          className="ml-auto rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
        >
          <option value="">Select investigation…</option>
          {cases.map((c) => (
            <option key={c.id} value={c.id}>{c.code} — {c.name}</option>
          ))}
        </select>
      </div>

      {!selected && <div className="text-sm text-muted">Choose an investigation to plot its located observations.</div>}

      {selected && (
        <>
          <div className="mb-2 kai-metadata">{points.length} located observation(s)</div>
          <div className="overflow-hidden rounded-lg border border-line" style={{ height: 480 }}>
            <MapContainer center={center} zoom={points.length ? 5 : 2} style={{ height: "100%", width: "100%", background: "#0e131d" }}>
              <TileLayer
                attribution='&copy; OpenStreetMap'
                url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              />
              {points.map((p) => (
                <CircleMarker key={p.entity_id} center={[p.lat, p.lon]} radius={7} pathOptions={{ color: "#e5484d", fillColor: "#e5484d", fillOpacity: 0.6 }}>
                  <Popup>
                    <div style={{ fontSize: 12 }}>
                      <strong>{p.label}</strong>
                      <br />
                      {p.type} · {p.lat.toFixed(4)}, {p.lon.toFixed(4)}
                    </div>
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>
          </div>
          {points.length === 0 && (
            <div className="mt-3 text-sm text-muted">
              No located entities. Add a <span className="font-mono">location</span> entity with
              lat/lon metadata (or a "lat,lon" value) to see it here.
            </div>
          )}
        </>
      )}
    </div>
  );
}
