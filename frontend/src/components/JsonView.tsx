import { useState } from "react";

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

function Scalar({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="text-muted">null</span>;
  if (typeof v === "string") return <span style={{ color: "var(--kai-verified)" }} className="break-words">{v}</span>;
  if (typeof v === "number") return <span style={{ color: "#f59e0b" }}>{String(v)}</span>;
  return <span style={{ color: "var(--kai-hud)" }}>{String(v)}</span>;
}

function Node({ k, v, depth }: { k?: string; v: unknown; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  const label = k !== undefined ? <span className="text-muted">{k}: </span> : null;
  if (!isObj(v)) return <div className="py-0.5">{label}<Scalar v={v} /></div>;
  const entries = Array.isArray(v) ? v.map((x, i) => [String(i), x] as const) : Object.entries(v);
  const summary = Array.isArray(v) ? `[${entries.length}]` : `{${entries.length}}`;
  if (entries.length === 0) return <div className="py-0.5">{label}<span className="text-muted">{Array.isArray(v) ? "[]" : "{}"}</span></div>;
  return (
    <div className="py-0.5">
      <button onClick={() => setOpen(!open)} className="text-left hover:text-ink">
        <span className="text-muted">{open ? "▾" : "▸"} </span>{label}<span className="text-muted">{summary}</span>
      </button>
      {open && (
        <div className="ml-3 border-l border-line/60 pl-3">
          {entries.map(([ck, cv]) => <Node key={ck} k={ck} v={cv} depth={depth + 1} />)}
        </div>
      )}
    </div>
  );
}

/** Collapsible, colour-coded view of a JSON value (instead of a raw dump). */
export function JsonView({ value }: { value: unknown }) {
  return (
    <div className="mt-1 max-h-64 overflow-auto rounded border border-line bg-panel p-2 font-mono text-[11px]">
      <Node v={value} depth={0} />
    </div>
  );
}
