import { useState } from "react";
import { Users } from "lucide-react";
import type { Edge, KinEntry, Relations, RelationNode, SharedFact } from "@/lib/investigate";
import { visibleEdges } from "@/lib/investigate";

const isUrl = (s: string | null | undefined) => !!s && /^https?:\/\//i.test(s);

function pctColor(p: number) {
  return p >= 70 ? "var(--kai-verified)" : p >= 55 ? "var(--kai-warn)" : "var(--kai-muted)";
}

function Badge({ children, color }: { children: string; color?: string }) {
  return (
    <span className="rounded border border-line px-1 text-[10px]" style={{ color: color ?? "var(--kai-muted)" }}>
      {children}
    </span>
  );
}

function SharedChip({ s }: { s: SharedFact }) {
  const label = `${s.what}: ${s.value}`;
  const cls = "rounded border px-1.5 py-0.5 text-xs";
  const style = { borderColor: "var(--kai-border)", color: "var(--kai-muted)" };
  if (isUrl(s.source_ref)) {
    return (
      <a href={s.source_ref} target="_blank" rel="noopener noreferrer" title={`${s.source}: ${s.source_ref}`}
        className={`${cls} hover:underline`} style={{ ...style, color: "var(--kai-hud)" }}>
        {label}
      </a>
    );
  }
  return <span className={cls} style={style} title={`${s.source}: ${s.source_ref}`}>{label}</span>;
}

type Open = (nid: string | null, name: string) => void;

function PersonRow({ disabled, name, sub, nid, webOnly, ambiguous, confidence, unconfirmed, onOpen, children }: {
  name: string;
  sub?: string;
  nid: string | null;
  webOnly: boolean;
  ambiguous: boolean;
  confidence?: number;
  unconfirmed?: boolean;
  onOpen: Open;
  disabled: boolean;
  children?: React.ReactNode;
}) {
  const head = (
    <div className="flex items-center gap-2">
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium">{name}</div>
        {sub && <div className="kai-metadata truncate">{sub}</div>}
      </div>
      {webOnly && <Badge color="var(--kai-warn)">not in system</Badge>}
      {ambiguous && <Badge color="var(--kai-warn)">ambiguous</Badge>}
      {unconfirmed && <Badge>unconfirmed</Badge>}
      {confidence != null && (
        <span className="hud-mono text-xs" style={{ color: pctColor(confidence) }}>{confidence}%</span>
      )}
    </div>
  );
  const clickable = !ambiguous && (nid != null || webOnly);
  return (
    <div className="rounded border border-line bg-panel p-1.5">
      {clickable ? (
        <button type="button" disabled={disabled} aria-disabled={disabled}
          className="block w-full text-left hover:bg-panel-2 disabled:opacity-40" title="Open this person"
          onClick={() => onOpen(nid, name)}>
          {head}
        </button>
      ) : head}
      {children}
    </div>
  );
}

function findNode(nodes: RelationNode[], nid: string | null, name: string) {
  return nodes.find((n) => (nid ? n.nid === nid : !n.nid && n.name === name));
}

function kinSub(k: KinEntry) {
  return [k.label || k.relation, k.date_of_birth].filter(Boolean).join(" · ");
}

export function RelationsPanel({ relations, onOpen, disabled = false }: { relations: Relations | null; onOpen: Open; disabled?: boolean }) {
  const [showWeak, setShowWeak] = useState(false);
  if (!relations) return <div className="kai-metadata">No connections found.</div>;
  const { kin, nodes } = relations;
  const kinGroups: [string, KinEntry[]][] = [
    ["Partners", kin.partners], ["Parents", kin.parents], ["Children", kin.children],
    ["Siblings", kin.siblings], ["Extended", kin.extended],
  ];
  const kinShown = kinGroups.filter(([, l]) => l.length > 0);
  const edges = visibleEdges(relations.associates, relations.weak_associates, showWeak);
  const empty = kinShown.length === 0 && edges.length === 0;

  return (
    <div>
      <label className="mb-2 flex items-center gap-2 text-[11px] text-muted">
        <input type="checkbox" checked={showWeak} onChange={(e) => setShowWeak(e.target.checked)} />
        Show weak links
      </label>
      {empty && <div className="kai-metadata">No connections found.</div>}
      {kinShown.length > 0 && (
        <div className="mb-2">
          <div className="mb-1 flex items-center gap-1.5">
            <Users size={12} style={{ color: "var(--kai-hud)" }} />
            <span className="hud-mono text-[11px]" style={{ color: "var(--kai-hud)" }}>Kin</span>
          </div>
          {kinShown.map(([title, list]) => (
            <div key={title} className="mb-2">
              <div className="kai-metadata mb-1">{title} ({list.length})</div>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {list.map((k, i) => {
                  const node = findNode(nodes, k.nid, k.name);
                  const ambiguous = !!(k.ambiguous || node?.ambiguous);
                  const inSystem = k.nid != null || k.in_system === true;
                  return (
                    <PersonRow key={`${k.nid ?? k.name}-${i}`} name={k.name} sub={kinSub(k)} nid={k.nid}
                      webOnly={!inSystem && !ambiguous} ambiguous={ambiguous}
                      confidence={k.confidence} onOpen={onOpen} disabled={disabled} />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
      {edges.length > 0 && (
        <div>
          <div className="mb-1 flex items-center gap-1.5">
            <Users size={12} style={{ color: "var(--kai-hud)" }} />
            <span className="hud-mono text-[11px]" style={{ color: "var(--kai-hud)" }}>Associates ({edges.length})</span>
          </div>
          <div className="grid gap-1.5">
            {edges.map((e: Edge, i) => {
              const node = findNode(nodes, e.person_b, e.name_b);
              const ambiguous = !!node?.ambiguous;
              return (
                <PersonRow key={`${e.person_b ?? e.name_b}-${i}`} name={e.name_b} sub={e.relation}
                  nid={e.person_b} webOnly={e.person_b == null && !ambiguous} ambiguous={ambiguous}
                  confidence={e.confidence} unconfirmed={!e.confirmed} onOpen={onOpen} disabled={disabled}>
                  {e.shared.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {e.shared.map((s, j) => <SharedChip key={j} s={s} />)}
                    </div>
                  )}
                </PersonRow>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
