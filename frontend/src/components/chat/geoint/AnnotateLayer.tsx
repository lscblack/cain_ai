import { useCallback, useEffect, useRef, useState } from "react";
import { GeoJSON, CircleMarker, Polygon, Polyline, useMap } from "react-leaflet";
import { circleMarker, type LatLng, type Map as LeafletMap, type LeafletMouseEvent } from "leaflet";
import { MapPin, Pentagon, Ruler, Trash2, Check, X, Save, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

export type Tool = "pin" | "polygon" | "line";
export type AnnoFeature = {
  type: "Feature";
  geometry: { type: "Point" | "LineString" | "Polygon"; coordinates: any };
  properties: { id: string; kind: Tool; note?: string; length_km?: number };
};
export type FeatureCollection = { type: "FeatureCollection"; features: any[] };

const COLOR = "#f5a623";
let seq = 0;
const newId = () => `a${Date.now().toString(36)}${(seq++).toString(36)}`;

function lengthKm(coords: [number, number][]): number {
  let m = 0;
  for (let i = 1; i < coords.length; i++) {
    const [lo1, la1] = coords[i - 1], [lo2, la2] = coords[i];
    const r = Math.PI / 180, dLa = (la2 - la1) * r, dLo = (lo2 - lo1) * r;
    const a = Math.sin(dLa / 2) ** 2 + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dLo / 2) ** 2;
    m += 2 * 6371 * Math.asin(Math.sqrt(a));
  }
  return m;
}

/** Annotation state. Lives in MapCard so annotations survive basemap switches. */
export function useAnnotations() {
  const [tool, setToolState] = useState<Tool | null>(null);
  const [features, setFeatures] = useState<AnnoFeature[]>([]);
  const [draft, setDraft] = useState<[number, number][]>([]); // [lat, lon] vertices
  const [note, setNote] = useState("");
  const draftRef = useRef(draft); draftRef.current = draft;
  const toolRef = useRef(tool); toolRef.current = tool;
  const noteRef = useRef(note); noteRef.current = note;

  const commit = useCallback((f: Omit<AnnoFeature, "properties"> & { properties: Omit<AnnoFeature["properties"], "id" | "note"> }) => {
    const n = noteRef.current.trim();
    setFeatures((fs) => [...fs, { ...f, properties: { ...f.properties, id: newId(), ...(n ? { note: n } : {}) } } as AnnoFeature]);
    setNote("");
  }, []);

  const finish = useCallback((dropDup = false) => {
    let v = draftRef.current;
    if (dropDup && v.length > 1) v = v.slice(0, -1); // dblclick fires a 2nd click at the same spot
    const t = toolRef.current;
    if (t === "line" && v.length >= 2) {
      const c = v.map(([la, lo]) => [lo, la] as [number, number]);
      commit({ type: "Feature", geometry: { type: "LineString", coordinates: c }, properties: { kind: "line", length_km: Number(lengthKm(c).toFixed(3)) } });
    } else if (t === "polygon" && v.length >= 3) {
      const ring = v.map(([la, lo]) => [lo, la] as [number, number]);
      commit({ type: "Feature", geometry: { type: "Polygon", coordinates: [[...ring, ring[0]]] }, properties: { kind: "polygon" } });
    }
    setDraft([]);
  }, [commit]);

  const addPoint = useCallback((ll: LatLng) => {
    if (toolRef.current === "pin") {
      commit({ type: "Feature", geometry: { type: "Point", coordinates: [ll.lng, ll.lat] }, properties: { kind: "pin" } });
    } else if (toolRef.current) {
      setDraft((d) => [...d, [ll.lat, ll.lng]]);
    }
  }, [commit]);

  const setTool = useCallback((t: Tool | null) => { setDraft([]); setToolState(t); }, []);
  const remove = useCallback((id: string) => setFeatures((fs) => fs.filter((f) => f.properties.id !== id)), []);
  const clear = useCallback(() => { setFeatures([]); setDraft([]); }, []);
  const collection: FeatureCollection = { type: "FeatureCollection", features };
  return { tool, setTool, features, draft, note, setNote, addPoint, finish, remove, clear, collection };
}
export type AnnotationState = ReturnType<typeof useAnnotations>;

/**
 * Inside <MapContainer>: draws annotations + the in-progress draft, and (only while a
 * tool is active) registers click/dblclick handlers on the map. The effect cleanup
 * ALWAYS removes them: on tool toggle-off, tool change, fullscreen toggle (dep) and unmount.
 */
export function AnnotateMapLayer({ s, fullscreen, mapRef }: {
  s: AnnotationState; fullscreen: boolean; mapRef: React.MutableRefObject<LeafletMap | null>;
}) {
  const map = useMap();
  const { tool, addPoint, finish } = s;
  useEffect(() => { mapRef.current = map; return () => { mapRef.current = null; }; }, [map, mapRef]);

  useEffect(() => {
    if (!tool) return;
    const onClick = (e: LeafletMouseEvent) => addPoint(e.latlng);
    const onDbl = () => finish(true);
    map.on("click", onClick);
    map.on("dblclick", onDbl);
    map.doubleClickZoom.disable();
    map.getContainer().style.cursor = "crosshair";
    return () => {
      map.off("click", onClick);
      map.off("dblclick", onDbl);
      map.doubleClickZoom.enable();
      map.getContainer().style.cursor = "";
    };
  }, [map, tool, fullscreen, addPoint, finish]);

  return (
    <>
      <SavedFeatures collections={[s.collection]} color={COLOR} />
      {s.draft.map((p, i) => (
        <CircleMarker key={`d${i}`} center={p} radius={3} pathOptions={{ color: COLOR, fillColor: COLOR, fillOpacity: 1 }} />
      ))}
      {s.tool === "polygon" && s.draft.length >= 2 && <Polygon positions={s.draft} pathOptions={{ color: COLOR, dashArray: "4 4", weight: 2 }} />}
      {s.tool === "line" && s.draft.length >= 2 && <Polyline positions={s.draft} pathOptions={{ color: COLOR, dashArray: "4 4", weight: 2 }} />}
    </>
  );
}

const GEOM_TYPES = ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"];

/** Keep only features Leaflet can build a layer for (null geometry or a known type). */
function safeFeatures(fc: FeatureCollection): any[] {
  return (Array.isArray(fc?.features) ? fc.features : []).filter(
    (f: any) => f && typeof f === "object" && (f.geometry == null || GEOM_TYPES.includes(f.geometry?.type)),
  );
}

/** Read-only GeoJSON renderer (saved evidence + live annotations). Inside <MapContainer>. */
export function SavedFeatures({ collections, color = "#a855f7" }: { collections: FeatureCollection[]; color?: string }) {
  return (
    <>
      {collections.map((raw, i) => {
        const fc: FeatureCollection = { ...raw, features: safeFeatures(raw) };
        return (
        <GeoJSON
          key={`${i}-${JSON.stringify(fc.features.map((f: any) => f?.properties?.id ?? f?.geometry?.coordinates))}`}
          data={fc as any}
          style={() => ({ color, weight: 3, fillOpacity: 0.15 })}
          pointToLayer={(_f, ll) => circleMarker(ll, { radius: 7, color, fillColor: color, fillOpacity: 0.7 })}
          onEachFeature={(f, layer) => {
            const p: any = f.properties || {};
            const txt = [p.note, p.length_km != null ? `${p.length_km} km` : null].filter(Boolean).join(" · ");
            if (txt) layer.bindPopup(txt.replace(/</g, "&lt;"));
          }}
        />
        );
      })}
    </>
  );
}

const btn = "flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] hover:bg-panel disabled:opacity-40";

/** Control rows (outside the map): tool toggle, note, list+delete, and Save to investigation. */
export function AnnotateControls({ s, layerId, dates, providerUrl, mapRef, onSaved }: {
  s: AnnotationState; layerId: string; dates: string[]; providerUrl: string;
  mapRef: React.MutableRefObject<LeafletMap | null>; onSaved?: (investigationId: string) => void;
}) {
  const [cases, setCases] = useState<InvestigationDetail[] | null>(null);
  const [caseId, setCaseId] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (cases || s.features.length === 0) return;
    investigationsApi.list().then(setCases).catch(() => { setCases([]); setMsg({ ok: false, text: "Couldn't load cases." }); });
  }, [s.features.length, cases]);

  const tools: { t: Tool; label: string; Icon: typeof MapPin }[] = [
    { t: "pin", label: "Pin", Icon: MapPin },
    { t: "polygon", label: "Area", Icon: Pentagon },
    { t: "line", label: "Line", Icon: Ruler },
  ];

  async function save() {
    const b = mapRef.current?.getBounds();
    if (!caseId || !b) return;
    setSaving(true); setMsg(null);
    try {
      await api.post("/geoint/evidence", {
        investigation_id: caseId,
        annotations: s.collection,
        layer_id: layerId,
        dates,
        bounds: { n: b.getNorth(), s: b.getSouth(), e: b.getEast(), w: b.getWest() },
        provider_url: providerUrl,
        ...(s.features.find((f) => f.properties.note)?.properties.note
          ? { note: s.features.filter((f) => f.properties.note).map((f) => f.properties.note).join("; ").slice(0, 2000) } : {}),
      });
      setMsg({ ok: true, text: "Saved to investigation." });
      s.clear(); s.setTool(null);
      onSaved?.(caseId);
    } catch {
      setMsg({ ok: false, text: "Save failed." });
    } finally { setSaving(false); }
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-1 px-2 py-1" style={{ background: "#0e131d" }}>
        <Pentagon size={10} className="text-muted" />
        <span className="kai-metadata mr-1">annotate:</span>
        {tools.map(({ t, label, Icon }) => (
          <button key={t} onClick={() => s.setTool(s.tool === t ? null : t)} className={btn}
            style={{ borderColor: s.tool === t ? "var(--kai-hud-dim)" : "var(--kai-border)", color: s.tool === t ? "var(--kai-hud)" : "var(--kai-muted)" }}>
            <Icon size={10} /> {label}
          </button>
        ))}
        {s.tool && (
          <>
            <input value={s.note} onChange={(e) => s.setNote(e.target.value)} placeholder="note (optional)" maxLength={200}
              className="rounded border border-line bg-transparent px-1.5 py-0.5 text-[10px]" />
            {s.tool !== "pin" && (
              <>
                <button onClick={() => s.finish()} disabled={s.draft.length < (s.tool === "polygon" ? 3 : 2)} className={btn} style={{ color: "var(--kai-hud)", borderColor: "var(--kai-border)" }}>
                  <Check size={10} /> Finish
                </button>
                <button onClick={() => s.setTool(s.tool)} disabled={s.draft.length === 0} className={btn} style={{ color: "var(--kai-muted)", borderColor: "var(--kai-border)" }}>
                  <X size={10} /> Cancel
                </button>
              </>
            )}
            <span className="kai-metadata">{s.tool === "pin" ? "click map to drop a pin" : "click vertices; double-click or Finish"}</span>
          </>
        )}
      </div>

      {s.features.length > 0 && (
        <div className="border-t px-2 py-1" style={{ borderColor: "#1a1e27" }}>
          {s.features.map((f) => (
            <div key={f.properties.id} className="flex items-center gap-2 py-0.5 text-[11px]">
              <span className="w-10 text-muted">{f.properties.kind}</span>
              <span className="flex-1 truncate">
                {f.properties.note || "—"}{f.properties.length_km != null ? ` · ${f.properties.length_km} km` : ""}
              </span>
              <button onClick={() => s.remove(f.properties.id)} title="Delete annotation" className="text-muted hover:text-ink"><Trash2 size={11} /></button>
            </div>
          ))}
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <select value={caseId} onChange={(e) => setCaseId(e.target.value)}
              className="rounded border border-line bg-panel px-1.5 py-0.5 text-[10px]">
              <option value="">{cases ? "Pick a case…" : "Loading cases…"}</option>
              {(cases ?? []).map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
            </select>
            <button onClick={save} disabled={!caseId || saving} className={btn} style={{ color: "var(--kai-hud)", borderColor: "var(--kai-border)" }}>
              {saving ? <Loader2 size={10} className="kai-spin" /> : <Save size={10} />} Save to investigation
            </button>
          </div>
        </div>
      )}
      {msg && (
        <div className="px-2 py-1 text-[10px]" style={{ color: msg.ok ? "var(--kai-verified)" : "var(--kai-accent)" }}>{msg.text}</div>
      )}
    </>
  );
}
