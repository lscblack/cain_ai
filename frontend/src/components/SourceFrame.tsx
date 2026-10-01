import { useEffect, useState } from "react";
import { X, ExternalLink } from "lucide-react";

export interface SourceContext {
  url: string;
  title?: string | null;
  caption?: string | null;
  names?: string[];
  imageUrl?: string | null;
}

/** Modal that opens a source page in an in-app iframe, with context + fallback.
 * Many sites block framing (X-Frame-Options/CSP) — we show an "open in new tab"
 * fallback and detect load failures. */
export function SourceFrame({ ctx, onClose }: { ctx: SourceContext; onClose: () => void }) {
  const [blocked, setBlocked] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setBlocked((b) => b), 100); // noop; load handler drives state
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onEsc);
    return () => { clearTimeout(t); window.removeEventListener("keydown", onEsc); };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="flex h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-line bg-panel" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-line p-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{ctx.title || ctx.url}</div>
            {ctx.caption && <div className="kai-metadata truncate">{ctx.caption}</div>}
            {ctx.names && ctx.names.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {ctx.names.slice(0, 8).map((n) => (
                  <span key={n} className="rounded border border-line px-2 py-0.5 text-xs" style={{ color: "var(--kai-warn)" }}>{n}</span>
                ))}
                <span className="kai-metadata self-center">possible names (unverified)</span>
              </div>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <a href={ctx.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded-md border border-line px-3 py-1.5 text-xs hover:bg-panel-2">
              <ExternalLink size={13} /> Open tab
            </a>
            <button onClick={onClose} className="rounded-md border border-line p-1.5 hover:bg-panel-2"><X size={14} /></button>
          </div>
        </div>
        <div className="relative flex-1 bg-white">
          <iframe
            src={ctx.url}
            title="source"
            className="h-full w-full"
            sandbox="allow-same-origin allow-scripts allow-popups"
            onError={() => setBlocked(true)}
          />
          {blocked && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-panel text-center">
              <div className="text-sm text-muted">This site blocks embedding.</div>
              <a href={ctx.url} target="_blank" rel="noreferrer" className="rounded-md border border-line px-4 py-2 text-sm hover:bg-panel-2">Open in new tab ↗</a>
            </div>
          )}
        </div>
        <div className="border-t border-line p-2">
          <a href={ctx.url} target="_blank" rel="noreferrer" className="kai-metadata truncate hover:text-ink">{ctx.url}</a>
        </div>
      </div>
    </div>
  );
}
