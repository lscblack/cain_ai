import { useCallback, useEffect, useRef, useState } from "react";
import { TileLayer, useMap } from "react-leaflet";
import type { LayerDef } from "@/components/chat/geoint/layers";
import { layerUrl } from "@/components/chat/geoint/layers";

export type CompareMode = "single" | "swipe" | "opacity";

const isoDay = (offsetDays: number) => new Date(Date.now() - offsetDays * 86400000).toISOString().slice(0, 10);

export type DateCompareState = ReturnType<typeof useDateCompare>;

/** State for the date picker / compare modes. Lives in MapCard so dates survive basemap switches. */
export function useDateCompare() {
  const [mode, setMode] = useState<CompareMode>("single");
  const [date, setDate] = useState(isoDay(1)); // single-date picker
  const [dateA, setDateA] = useState(isoDay(30));
  const [dateB, setDateB] = useState(isoDay(1));
  const [split, setSplit] = useState(0.5); // swipe divider, fraction of map width
  const [opacity, setOpacity] = useState(0.5); // B layer opacity in "opacity" mode
  const [empty, setEmpty] = useState<{ A: boolean; B: boolean; S: boolean }>({ A: false, B: false, S: false });
  const counts = useRef<Record<string, { ok: number; err: number }>>({});

  // Fresh error accounting whenever a chosen date changes.
  useEffect(() => { counts.current = {}; setEmpty({ A: false, B: false, S: false }); }, [date, dateA, dateB]);

  const onTile = useCallback((slot: "A" | "B" | "S", failed: boolean) => {
    const c = (counts.current[slot] ??= { ok: 0, err: 0 });
    if (failed) c.err++; else c.ok++;
    const isEmpty = c.ok === 0 && c.err >= 3;
    setEmpty((e) => (e[slot] === isEmpty ? e : { ...e, [slot]: isEmpty }));
  }, []);

  return { mode, setMode, date, setDate, dateA, setDateA, dateB, setDateB, split, setSplit, opacity, setOpacity, empty, onTile };
}

/** Control row, shown only for dated bases. */
export function DateCompareControls({ s }: { s: DateCompareState }) {
  const max = isoDay(0);
  const inputCls = "rounded border border-line bg-transparent px-1 py-0.5 font-mono text-[10px]";
  const btn = (m: CompareMode, label: string) => (
    <button key={m} onClick={() => s.setMode(m)}
      className="rounded border px-1.5 py-0.5 text-[10px] hover:bg-panel"
      style={{ borderColor: s.mode === m ? "var(--kai-hud-dim)" : "var(--kai-border)", color: s.mode === m ? "var(--kai-hud)" : "var(--kai-muted)" }}>
      {label}
    </button>
  );
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b px-2 py-1 text-[10px]" style={{ borderColor: "#1a1e27", background: "#11151d", color: "#6b7280" }}>
      <span>Date</span>
      {s.mode === "single" ? (
        <input type="date" className={inputCls} max={max} value={s.date} onChange={(e) => e.target.value && s.setDate(e.target.value)} />
      ) : (
        <>
          <span>A</span>
          <input type="date" className={inputCls} max={max} value={s.dateA} onChange={(e) => e.target.value && s.setDateA(e.target.value)} />
          <span>B</span>
          <input type="date" className={inputCls} max={max} value={s.dateB} onChange={(e) => e.target.value && s.setDateB(e.target.value)} />
        </>
      )}
      {s.mode === "opacity" && (
        <input type="range" min={0} max={1} step={0.01} value={s.opacity} onChange={(e) => s.setOpacity(Number(e.target.value))}
          title="Cross-fade A to B" aria-label="Cross-fade A to B" />
      )}
      <div className="ml-auto flex items-center gap-1">
        {btn("single", "Single")}{btn("swipe", "Swipe")}{btn("opacity", "Fade")}
      </div>
      {(s.empty.S || s.empty.A || s.empty.B) && (
        <span className="basis-full" style={{ color: "#f5a623" }}>
          No imagery this date{s.mode === "single" ? "" : ` (${[s.empty.A && "A", s.empty.B && "B"].filter(Boolean).join(", ")})`}
          {s.mode === "single" ? "" : " — other date still shown"}
        </span>
      )}
    </div>
  );
}

/** Draggable vertical divider; render inside a `relative` wrapper around the map. */
export function SwipeHandle({ s }: { s: DateCompareState }) {
  const drag = (e: React.PointerEvent<HTMLDivElement>) => {
    const parent = e.currentTarget.parentElement!;
    e.currentTarget.setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      const r = parent.getBoundingClientRect();
      s.setSplit(Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)));
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div onPointerDown={drag} role="slider" aria-label="Swipe divider" aria-valuenow={Math.round(s.split * 100)}
      style={{ position: "absolute", top: 0, bottom: 0, left: `calc(${s.split * 100}% - 12px)`, width: 24, zIndex: 1100, cursor: "ew-resize", touchAction: "none", display: "flex", justifyContent: "center" }}>
      <div style={{ width: 2, background: "#22d3ee", boxShadow: "0 0 4px #000" }} />
      <div style={{ position: "absolute", top: "50%", marginTop: -12, width: 24, height: 24, borderRadius: 12, background: "#11151d", border: "2px solid #22d3ee", color: "#22d3ee", fontSize: 10, display: "flex", alignItems: "center", justifyContent: "center" }}>⇆</div>
    </div>
  );
}

const PANE = "kai-compare-b";

/** Inside <MapContainer>: single-date base, or stacked A (under) / B (over, own pane). */
export function DateLayers({ base, s }: { base: LayerDef; s: DateCompareState }) {
  const map = useMap();
  const [paneReady, setPaneReady] = useState(false);

  useEffect(() => {
    const pane = map.getPane(PANE) ?? map.createPane(PANE);
    pane.style.zIndex = "250"; // above tilePane (200), below overlays/markers
    setPaneReady(true);
  }, [map]);

  // Clip the B pane to the divider (layer-space x) so left=A, right=B.
  useEffect(() => {
    const pane = map.getPane(PANE);
    if (!pane) return;
    const apply = () => {
      if (s.mode !== "swipe") { pane.style.clipPath = ""; return; }
      const x = map.containerPointToLayerPoint([s.split * map.getSize().x, 0]).x;
      pane.style.clipPath = `polygon(${x}px -100000px, 100000px -100000px, 100000px 100000px, ${x}px 100000px)`;
    };
    apply();
    map.on("move zoom viewreset resize", apply);
    return () => { map.off("move zoom viewreset resize", apply); pane.style.clipPath = ""; };
  }, [map, s.mode, s.split, paneReady]);

  const common = { attribution: base.attribution, maxNativeZoom: base.max_zoom, maxZoom: 19 };
  if (s.mode === "single") {
    return <TileLayer key={`${base.id}-S`} {...common} url={layerUrl(base, s.date)}
      eventHandlers={{ tileerror: () => s.onTile("S", true), tileload: () => s.onTile("S", false) }} />;
  }
  return (
    <>
      <TileLayer key={`${base.id}-A`} {...common} url={layerUrl(base, s.dateA)}
        eventHandlers={{ tileerror: () => s.onTile("A", true), tileload: () => s.onTile("A", false) }} />
      {paneReady && (
        <TileLayer key={`${base.id}-B`} {...common} pane={PANE} url={layerUrl(base, s.dateB)}
          opacity={s.mode === "opacity" ? s.opacity : 1}
          eventHandlers={{ tileerror: () => s.onTile("B", true), tileload: () => s.onTile("B", false) }} />
      )}
    </>
  );
}
