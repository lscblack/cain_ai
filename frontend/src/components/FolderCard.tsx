import { Link } from "react-router-dom";
import { Folder, Trash2 } from "lucide-react";

/** A manila-folder-style case card (HUD cyan). Links to the case. */
export function FolderCard({
  to,
  code,
  title,
  status,
  statusColor,
  meta,
  onDelete,
}: {
  to: string;
  code: string;
  title: string;
  status: string;
  statusColor: string;
  meta: { label: string; value: string | number }[];
  onDelete?: () => void;
}) {
  return (
    <Link to={to} className="group relative block transition hover:brightness-125">
      {onDelete && (
        <button
          type="button"
          title="Delete case"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDelete();
          }}
          className="absolute right-1.5 top-6 z-10 rounded border border-line bg-panel p-1 opacity-0 transition hover:border-[color:var(--kai-accent)] group-hover:opacity-100"
          style={{ color: "var(--kai-accent)" }}
        >
          <Trash2 size={13} />
        </button>
      )}
      {/* folder tab */}
      <div
        className="flex h-5 w-28 items-center gap-1 rounded-t-md border border-b-0 px-2"
        style={{ borderColor: "var(--kai-hud-dim)", background: "var(--kai-panel-2)" }}
      >
        <Folder size={11} style={{ color: "var(--kai-hud)" }} />
        <span className="truncate font-mono text-[9px]" style={{ color: "var(--kai-hud)" }}>
          {code}
        </span>
      </div>
      {/* folder body */}
      <div
        className="hud-scanlines rounded-b-md rounded-tr-md border p-4"
        style={{
          borderColor: "var(--kai-hud-dim)",
          background: "var(--kai-panel-2)",
          boxShadow: "inset 0 0 24px rgba(34,211,238,0.05)",
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 truncate text-sm font-semibold group-hover:text-ink">{title}</div>
          <span className="shrink-0 hud-mono text-[10px] uppercase tracking-wider" style={{ color: statusColor }}>
            {status}
          </span>
        </div>
        <div className="kai-metadata mt-3 flex flex-wrap gap-3">
          {meta.map((m) => (
            <span key={m.label}>
              {m.label} <span style={{ color: "var(--kai-hud)" }}>{m.value}</span>
            </span>
          ))}
        </div>
      </div>
    </Link>
  );
}
