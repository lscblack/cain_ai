import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { AuthImg } from "@/components/AuthImg";

interface GraphFace {
  face_id: string;
  crop_url?: string | null;
}
interface Connection {
  face_id: string;
  crop_url?: string | null;
  names?: string[];
  page_title?: string | null;
  source_url?: string | null;
  reasons?: string[];
  connection?: string;
}

function reasonLabel(r?: string): string {
  if (!r) return "linked";
  if (r === "co_located") return "same page";
  if (r.startsWith("shares:")) return `shares ${r.slice(7)}`;
  return r;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

/** Associated-people graph: the subject at centre, people connected via public
 *  co-occurrence (same page / shared identifier) on spokes. Potential links —
 *  not confirmed family or contacts. Edges come from /intelligence/face/{id}/connections. */
export function FamilyGraph({
  term,
  faces,
}: {
  term: string;
  faces: GraphFace[];
}) {
  const [loading, setLoading] = useState(false);
  const [conns, setConns] = useState<Connection[] | null>(null);

  useEffect(() => {
    let active = true;
    const ids = faces.map((f) => f.face_id).slice(0, 4);
    if (ids.length === 0) {
      setConns([]);
      return;
    }
    setLoading(true);
    setConns(null);
    (async () => {
      const merged = new Map<string, Connection>();
      for (const id of ids) {
        try {
          const r = await api.get<{ connections: Connection[] }>(
            `/intelligence/face/${id}/connections`,
          );
          for (const c of r.connections ?? []) {
            const key = (c.names?.[0] ?? c.page_title ?? c.face_id).toLowerCase();
            if (!merged.has(key)) merged.set(key, c);
          }
        } catch {
          /* skip a face that errors */
        }
      }
      if (active) {
        setConns([...merged.values()].slice(0, 14));
        setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [term, faces.map((f) => f.face_id).join(",")]);

  const subjectCrop = faces[0]?.crop_url ?? null;

  const nodes = (conns ?? []).map((c, i, arr) => {
    const angle = (i / Math.max(1, arr.length)) * Math.PI * 2 - Math.PI / 2;
    const r = 38; // % radius
    return {
      c,
      x: 50 + r * Math.cos(angle),
      y: 50 + r * Math.sin(angle),
    };
  });

  return (
    <div className="hud-panel hud-frame mt-4 p-4">
      <div className="mb-1 hud-mono text-xs uppercase hud-glow" style={{ color: "var(--kai-hud)" }}>
        ◢ Associated people (potential)
      </div>
      <div className="kai-metadata mb-3">
        Linked by public co-occurrence (same page) or shared identifiers — not confirmed family or
        contacts.
      </div>

      {loading ? (
        <div className="kai-metadata py-8 text-center">mapping connections…</div>
      ) : (conns?.length ?? 0) === 0 ? (
        <div className="kai-metadata py-8 text-center">No associations found in the local index.</div>
      ) : (
        <div className="relative w-full hud-scanlines" style={{ aspectRatio: "16 / 10" }}>
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
            {nodes.map((n, i) => (
              <g key={i}>
                <line
                  x1={50}
                  y1={50}
                  x2={n.x}
                  y2={n.y}
                  stroke="var(--kai-hud)"
                  strokeWidth={0.3}
                  strokeOpacity={0.5}
                  strokeDasharray={n.c.connection === "co_location" ? "1.5 1.5" : undefined}
                />
                <text
                  x={(50 + n.x) / 2}
                  y={(50 + n.y) / 2 - 1}
                  fill="var(--kai-muted)"
                  fontSize={2.2}
                  textAnchor="middle"
                  style={{ fontFamily: "JetBrains Mono, monospace" }}
                >
                  {reasonLabel(n.c.reasons?.[0])}
                </text>
              </g>
            ))}
          </svg>

          {/* centre subject */}
          <Node x={50} y={50} crop={subjectCrop} label={term} center />
          {/* spokes */}
          {nodes.map((n, i) => (
            <Node
              key={i}
              x={n.x}
              y={n.y}
              crop={n.c.crop_url}
              label={n.c.names?.[0] ?? n.c.page_title ?? n.c.face_id.slice(0, 6)}
              href={n.c.source_url ?? undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Node({
  x,
  y,
  crop,
  label,
  center,
  href,
}: {
  x: number;
  y: number;
  crop?: string | null;
  label: string;
  center?: boolean;
  href?: string;
}) {
  const size = center ? 64 : 44;
  const body = (
    <div className="flex flex-col items-center" style={{ width: size + 24 }}>
      <div
        className="overflow-hidden rounded-full"
        style={{
          width: size,
          height: size,
          border: `2px solid var(--kai-hud)`,
          boxShadow: center ? "0 0 14px rgba(34,211,238,0.6)" : "0 0 8px rgba(34,211,238,0.35)",
        }}
      >
        {crop ? (
          <AuthImg path={crop} className="h-full w-full object-cover" />
        ) : (
          <div
            className="flex h-full w-full items-center justify-center text-xs"
            style={{ background: "var(--kai-panel-2)", color: "var(--kai-hud)" }}
          >
            {initials(label)}
          </div>
        )}
      </div>
      <span
        className="mt-1 max-w-full truncate text-center text-[10px]"
        style={{ color: center ? "var(--kai-hud)" : "var(--kai-text)" }}
        title={label}
      >
        {label}
      </span>
    </div>
  );
  const style: React.CSSProperties = {
    position: "absolute",
    left: `${x}%`,
    top: `${y}%`,
    transform: "translate(-50%, -50%)",
  };
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" style={style}>
      {body}
    </a>
  ) : (
    <div style={style}>{body}</div>
  );
}
