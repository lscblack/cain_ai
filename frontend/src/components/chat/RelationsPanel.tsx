import { useState } from "react";
import { Globe, Users } from "lucide-react";
import type { Edge, Fact, KinEntry, PersonRef, Relations, RelationNode, SharedFact, WebFinding } from "@/lib/investigate";
import { isHttpUrl, visibleEdges } from "@/lib/investigate";

const MAX_WEB_ROWS = 10;

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
  if (isHttpUrl(s.source_ref)) {
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

function PersonRow({ disabled, name, sub, nid, webOnly, ambiguous, confidence, tags = [], onOpen, children }: {
  name: string;
  sub?: string;
  nid: string | null;
  webOnly: boolean;
  ambiguous: boolean;
  confidence?: number;
  /** muted badges such as "inferred" or "unconfirmed" */
  tags?: string[];
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
      {tags.map((t) => <Badge key={t}>{t}</Badge>)}
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

/** Partners are inferred from children who name both parents. */
function partnerSub(k: KinEntry) {
  const n = Array.isArray(k.children) ? k.children.length : 0;
  return n === 1 ? "inferred from 1 shared child" : `inferred from ${n} shared children`;
}

/** Associate edges are inferences; web-only edges keep the "unconfirmed" wording. */
function edgeTag(e: Edge) {
  return e.shared.length > 0 && e.shared.every((s) => s.source === "web") ? "unconfirmed" : "inferred";
}

function SectionTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mb-1 flex items-center gap-1.5">
      {icon}
      <span className="hud-mono text-[11px]" style={{ color: "var(--kai-hud)" }}>{children}</span>
    </div>
  );
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
                  const partner = title === "Partners";
                  return (
                    <PersonRow key={`${k.nid ?? k.name}-${i}`} name={k.name}
                      sub={partner ? partnerSub(k) : kinSub(k)} nid={k.nid}
                      webOnly={!inSystem && !ambiguous} ambiguous={ambiguous}
                      tags={partner ? ["unconfirmed"] : []}
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
                  confidence={e.confidence} tags={[edgeTag(e)]} onOpen={onOpen} disabled={disabled}>
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

/** Compact card for the person a view is about (fields shown only when present). */
export function PersonSummary({ person }: { person: PersonRef }) {
  const txt = (v: unknown) => (typeof v === "string" ? v.trim() : "");
  const place = [person.district, person.sector, person.cell, person.village].map(txt).filter(Boolean).join(" / ");
  const phones = Array.isArray(person.phones) ? person.phones.map(txt).filter(Boolean).join(", ") : "";
  const rows = ([
    ["NID", txt(person.nid)],
    ["Sex", txt(person.sex)],
    ["Date of birth", txt(person.date_of_birth)],
    ["Marital status", txt(person.marital_status)],
    ["Location", place],
    ["Phones", phones],
    ["Father", txt(person.father_names)],
    ["Mother", txt(person.mother_names)],
  ] as [string, string][]).filter(([, v]) => v);
  return (
    <div className="mb-2 rounded border border-line bg-panel p-2">
      <div className="truncate text-xs font-medium">{txt(person.name) || txt(person.nid)}</div>
      {rows.length > 0 && (
        <div className="mt-1 grid gap-x-3 gap-y-0.5 sm:grid-cols-2">
          {rows.map(([k, v]) => (
            <div key={k} className="min-w-0 truncate text-xs" title={`${k}: ${v}`}>
              <span className="kai-metadata">{k}: </span>{v}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WebFactRow({ f }: { f: Fact }) {
  return (
    <div className="flex items-center gap-2 rounded border border-line bg-panel p-1.5">
      <div className="min-w-0 flex-1 truncate text-xs">
        <span className="kai-metadata">{f.claim} — </span>
        {isHttpUrl(f.source_ref) ? (
          <a href={f.source_ref} target="_blank" rel="noopener noreferrer" title={f.source_ref}
            className="hover:underline" style={{ color: "var(--kai-hud)" }}>
            {f.value}
          </a>
        ) : <span title={f.source_ref}>{f.value}</span>}
      </div>
      <span className="hud-mono text-xs" style={{ color: pctColor(f.confidence) }}>{f.confidence}%</span>
    </div>
  );
}

/**
 * Web findings (rows from the web facts, which carry the confidence the bare
 * findings lack) and the spouses named on web pages.
 */
export function WebSection({ facts, findings, nodes = [], spouseCandidates = [], collision, onOpen, disabled = false }: {
  facts: Fact[];
  findings: WebFinding[];
  nodes?: RelationNode[];
  spouseCandidates?: string[];
  collision?: boolean;
  onOpen: Open;
  disabled?: boolean;
}) {
  const rows = facts.filter((f) => f.source === "web" && f.claim !== "reported spouse");
  const spouseNodes = nodes.filter((n) => n.relation === "reported spouse");
  // without relations (web-only card, no subject) only the names are known
  const spouseNames = spouseNodes.length > 0 ? [] : spouseCandidates;
  if (findings.length === 0 && rows.length === 0 && spouseNodes.length === 0 && spouseNames.length === 0) return null;
  return (
    <div className="mt-2">
      <SectionTitle icon={<Globe size={12} style={{ color: "var(--kai-hud)" }} />}>Web ({rows.length})</SectionTitle>
      {collision && (
        <div className="kai-metadata mb-1">Web results may refer to a different person with the same name.</div>
      )}
      {rows.length > 0 && (
        <div className="grid gap-1.5">
          {rows.slice(0, MAX_WEB_ROWS).map((f, i) => <WebFactRow key={`${f.id}-${i}`} f={f} />)}
        </div>
      )}
      {rows.length > MAX_WEB_ROWS && (
        <div className="kai-metadata mt-1">{rows.length - MAX_WEB_ROWS} more not shown.</div>
      )}
      {(spouseNodes.length > 0 || spouseNames.length > 0) && (
        <div className="mt-2">
          <div className="kai-metadata mb-1">Reported spouse (web, unconfirmed)</div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {spouseNodes.map((n, i) => {
              const ambiguous = !!n.ambiguous;
              return (
                <PersonRow key={`${n.nid ?? n.name}-${i}`} name={n.name} nid={n.in_system ? n.nid : null}
                  webOnly={!n.in_system && !ambiguous} ambiguous={ambiguous}
                  tags={["unconfirmed"]} onOpen={onOpen} disabled={disabled}>
                  {isHttpUrl(n.source_ref) && (
                    <a href={n.source_ref} target="_blank" rel="noopener noreferrer" title={n.source_ref}
                      className="kai-metadata mt-1 block truncate hover:underline" style={{ color: "var(--kai-hud)" }}>
                      source
                    </a>
                  )}
                </PersonRow>
              );
            })}
            {spouseNames.map((name, i) => (
              <PersonRow key={`${name}-${i}`} name={name} nid={null} webOnly={false} ambiguous={false}
                tags={["unconfirmed"]} onOpen={onOpen} disabled={disabled} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
