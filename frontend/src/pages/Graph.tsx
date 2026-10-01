import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Share2 } from "lucide-react";

import { investigationsApi } from "@/lib/investigations";
import type {
  CaseGraph,
  EntityNode,
  InvestigationDetail,
  RelationshipEdge,
  Suggestion,
} from "@/types";

const TYPE_COLOR: Record<string, string> = {
  face: "#e5484d",
  phone: "#30a46c",
  email: "#4593e5",
  username: "#a855f7",
  domain: "#f5a623",
  url: "#f5a623",
  image: "#e5484d",
  organization: "#8b93a7",
  location: "#30a46c",
  document: "#8b93a7",
  vehicle: "#8b93a7",
  aircraft: "#8b93a7",
  vessel: "#8b93a7",
};

interface Positioned extends EntityNode {
  x: number;
  y: number;
}

function layout(nodes: EntityNode[], w: number, h: number): Positioned[] {
  const cx = w / 2;
  const cy = h / 2;
  const r = Math.min(w, h) / 2 - 60;
  return nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1) - Math.PI / 2;
    return { ...n, x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  });
}

export function Graph() {
  const [params, setParams] = useSearchParams();
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [selected, setSelected] = useState(params.get("investigation") ?? "");
  const [graph, setGraph] = useState<CaseGraph | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [sel, setSel] = useState<
    | { kind: "node"; node: EntityNode }
    | { kind: "edge"; edge: RelationshipEdge }
    | null
  >(null);

  useEffect(() => {
    investigationsApi.list().then(setCases).catch(() => setCases([]));
  }, []);

  async function loadGraph(id: string) {
    if (!id) {
      setGraph(null);
      return;
    }
    const [g, c] = await Promise.all([
      investigationsApi.graph(id),
      investigationsApi.correlations(id).catch(() => ({ suggestions: [] })),
    ]);
    setGraph(g);
    setSuggestions(c.suggestions);
    setSel(null);
  }

  useEffect(() => {
    if (selected) loadGraph(selected);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const W = 720;
  const H = 460;
  const positioned = useMemo(() => (graph ? layout(graph.nodes, W, H) : []), [graph]);
  const posById = useMemo(() => {
    const m: Record<string, Positioned> = {};
    positioned.forEach((p) => (m[p.id] = p));
    return m;
  }, [positioned]);

  async function accept(s: Suggestion) {
    await investigationsApi.addRelationship(selected, {
      source_entity_id: s.source_entity_id,
      target_entity_id: s.target_entity_id,
      rel_type: s.rel_type,
      source_url: s.source_url,
    });
    await loadGraph(selected);
  }

  return (
    <div>
      <div className="mb-5 flex items-center gap-3">
        <Share2 size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Intelligence Graph</h1>
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
            <option key={c.id} value={c.id}>
              {c.code} — {c.name}
            </option>
          ))}
        </select>
      </div>

      {!selected && <div className="text-sm text-muted">Choose an investigation to view its evidence graph.</div>}

      {graph && (
        <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
          <div className="rounded-lg border border-line bg-panel-2">
            <svg viewBox={`0 0 ${W} ${H}`} className="h-[460px] w-full">
              {graph.edges.map((e) => {
                const a = posById[e.source_entity_id];
                const b = posById[e.target_entity_id];
                if (!a || !b) return null;
                return (
                  <line
                    key={e.id}
                    x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                    stroke={sel?.kind === "edge" && sel.edge.id === e.id ? "#e5484d" : "#2a3344"}
                    strokeWidth={sel?.kind === "edge" && sel.edge.id === e.id ? 2.5 : 1.5}
                    className="cursor-pointer"
                    onClick={() => setSel({ kind: "edge", edge: e })}
                  />
                );
              })}
              {positioned.map((n) => (
                <g key={n.id} className="cursor-pointer" onClick={() => setSel({ kind: "node", node: n })}>
                  <circle cx={n.x} cy={n.y} r={sel?.kind === "node" && sel.node.id === n.id ? 11 : 8}
                    fill={TYPE_COLOR[n.type] ?? "#8b93a7"} stroke="#0a0b0d" strokeWidth={2} />
                  <text x={n.x} y={n.y - 14} textAnchor="middle" fontSize="9" fill="#8b93a7" className="font-mono">
                    {n.value.length > 18 ? n.value.slice(0, 17) + "…" : n.value}
                  </text>
                </g>
              ))}
              {graph.nodes.length === 0 && (
                <text x={W / 2} y={H / 2} textAnchor="middle" fill="#8b93a7" fontSize="12">
                  No entities in this investigation yet.
                </text>
              )}
            </svg>
          </div>

          <div className="space-y-4">
            {/* evidence/detail panel */}
            <div className="rounded-lg border border-line bg-panel p-4">
              <div className="kai-metadata mb-2 uppercase">Details</div>
              {!sel && <div className="text-sm text-muted">Click a node or edge.</div>}
              {sel?.kind === "node" && (
                <div className="space-y-1 text-sm">
                  <div className="kai-metadata uppercase">{sel.node.type}</div>
                  <div className="font-mono">{sel.node.value}</div>
                  {sel.node.label && <div className="text-muted">{sel.node.label}</div>}
                </div>
              )}
              {sel?.kind === "edge" && (
                <div className="space-y-2 text-sm">
                  <div className="kai-metadata uppercase">why this connection exists</div>
                  <div>{sel.edge.rel_type.replace(/_/g, " ")}</div>
                  <a href={sel.edge.source_url} target="_blank" rel="noreferrer" className="block truncate text-xs hover:underline" style={{ color: "var(--kai-warn)" }}>
                    {sel.edge.source_url}
                  </a>
                  <div className="kai-metadata">observed {new Date(sel.edge.observed_at).toLocaleString()}</div>
                  {sel.edge.evidence_excerpt && <div className="text-muted">"{sel.edge.evidence_excerpt}"</div>}
                </div>
              )}
            </div>

            {/* correlation suggestions */}
            <div className="rounded-lg border border-line bg-panel p-4">
              <div className="kai-metadata mb-2 uppercase">Suggested links ({suggestions.length})</div>
              {suggestions.length === 0 ? (
                <div className="text-sm text-muted">No co-occurrence suggestions.</div>
              ) : (
                <div className="space-y-2">
                  {suggestions.map((s, i) => (
                    <div key={i} className="rounded-md border border-line px-3 py-2 text-xs">
                      <div className="text-muted">{s.reason}</div>
                      <button
                        onClick={() => accept(s)}
                        className="mt-2 rounded border border-line px-2 py-1 hover:bg-panel-2"
                        style={{ color: "var(--kai-verified)" }}
                      >
                        Accept as observed link
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
