import type { LayerDef } from "./layers";

const GROUPS: { title: string; match: (l: LayerDef) => boolean }[] = [
  { title: "Reference", match: (l) => l.kind === "base" && l.id.startsWith("osm") },
  { title: "Imagery", match: (l) => l.kind === "base" && !l.id.startsWith("osm") },
  { title: "Terrain", match: (l) => l.kind === "overlay" },
];

export function BasemapPicker({ layers, baseId, overlayIds, onBase, onToggleOverlay }: {
  layers: LayerDef[];
  baseId: string;
  overlayIds: string[];
  onBase: (id: string) => void;
  onToggleOverlay: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {GROUPS.map((g) => {
        const items = layers.filter(g.match);
        if (!items.length) return null;
        return (
          <div key={g.title} className="flex items-center gap-1">
            <span className="kai-metadata">{g.title}:</span>
            {items.map((l) => {
              const on = l.kind === "base" ? l.id === baseId : overlayIds.includes(l.id);
              return (
                <button key={l.id} title={`${l.label} ${l.kind === "base" ? "basemap" : "overlay"}`}
                  onClick={() => (l.kind === "base" ? onBase(l.id) : onToggleOverlay(l.id))}
                  className="rounded border px-1.5 py-0.5 text-[10px] hover:bg-panel"
                  style={{ borderColor: on ? "var(--kai-hud-dim)" : "var(--kai-border)", color: on ? "var(--kai-hud)" : "var(--kai-muted)" }}>
                  {l.label}
                </button>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
