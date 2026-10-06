import { useEffect, useRef, useState } from "react";
import { ListOrdered, RefreshCw, Trash2, Radar } from "lucide-react";

import { api } from "@/lib/api";

interface QueueDetail {
  queued: number;
  discovery_queued: number;
  crawling: { id: string; domain: string; since: string | null }[];
  queued_next: { id: string; domain: string }[];
}

export function Queue() {
  const [q, setQ] = useState<QueueDetail | null>(null);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  async function load() {
    setBusy(true);
    try {
      setQ(await api.get<QueueDetail>("/sources/queue?limit=2000"));
    } catch {
      setQ(null);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load();
    timer.current = setInterval(load, 6000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, []);

  async function clearQueue() {
    if (!confirm("Clear the entire crawl queue and reset stuck sources?")) return;
    const r = await api.post<{ cleared: number }>("/sources/queue/clear").catch(() => null);
    if (r) { alert(`Cleared ${r.cleared} queued crawl job(s).`); load(); }
  }

  const next = (q?.queued_next ?? []).filter((s) => !filter || s.domain.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="w-11/12 max-w-[1700px] mx-auto space-y-5">
      <header className="flex items-center gap-3">
        <ListOrdered className="text-accent" size={22} />
        <div>
          <h1 className="text-xl font-semibold tracking-wide">Crawl queue</h1>
          <p className="kai-metadata">Everything waiting to be crawled, in order</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={load} className="flex items-center gap-1.5 border border-line px-3 py-1.5 text-xs uppercase tracking-wider text-muted transition hover:border-accent hover:text-ink">
            <RefreshCw size={13} className={busy ? "animate-spin" : ""} /> Refresh
          </button>
          <button onClick={clearQueue} disabled={!q?.queued} className="flex items-center gap-1.5 border px-3 py-1.5 text-xs uppercase tracking-wider transition disabled:opacity-40"
            style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}>
            <Trash2 size={13} /> Clear queue
          </button>
        </div>
      </header>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Crawl queue" value={q?.queued ?? 0} accent />
        <Stat label="Crawling now" value={q?.crawling.length ?? 0} />
        <Stat label="Discovery queue" value={q?.discovery_queued ?? 0} icon />
      </div>

      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        <section className="border border-line bg-panel-2 p-4">
          <div className="mb-2 kai-metadata uppercase">Currently crawling ({q?.crawling.length ?? 0})</div>
          {(q?.crawling.length ?? 0) === 0 ? <p className="text-sm text-muted">— idle —</p> : (
            <div className="space-y-1">
              {q!.crawling.map((s) => (
                <div key={s.id} className="flex items-center gap-2 truncate font-mono text-xs">
                  <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full" style={{ background: "var(--kai-warn)" }} />
                  <span className="truncate text-ink">{s.domain}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="border border-line bg-panel-2 p-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="kai-metadata uppercase">
              Next up — showing {next.length} of {q?.queued ?? 0}
              {(q?.queued ?? 0) > (q?.queued_next.length ?? 0) ? ` (first ${q?.queued_next.length})` : ""}
            </span>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="filter domain…"
              className="w-40 border border-line bg-base px-2 py-1 font-mono text-xs text-ink outline-none focus:border-accent"
            />
          </div>
          {next.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted">{filter ? "No match." : "Queue is empty."}</p>
          ) : (
            <div className="max-h-[60vh] overflow-auto">
              <table className="w-full font-mono text-xs">
                <tbody>
                  {next.map((s, i) => (
                    <tr key={s.id + i} className="border-b border-line/50 hover:bg-panel">
                      <td className="w-10 py-1.5 pr-2 text-right text-muted">{i + 1}</td>
                      <td className="truncate py-1.5 text-ink">{s.domain}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Stat({ label, value, accent, icon }: { label: string; value: number; accent?: boolean; icon?: boolean }) {
  return (
    <div className="border border-line bg-panel-2 px-4 py-3">
      <div className={`flex items-center gap-2 text-2xl font-semibold ${accent ? "text-accent" : "text-ink"}`}>
        {icon && <Radar size={18} className="text-muted" />}{value.toLocaleString()}
      </div>
      <div className="kai-metadata mt-0.5">{label}</div>
    </div>
  );
}
