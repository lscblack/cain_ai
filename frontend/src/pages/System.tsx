import { useEffect, useState } from "react";
import { Activity } from "lucide-react";

import { api } from "@/lib/api";

interface Stats {
  resources: {
    cpu_percent?: number;
    cpu_cores?: number;
    cpu_process_percent?: number;
    cpu_process_cores?: number;
    cpu_process_threads?: number;
    ram_percent?: number;
    ram_used_mb?: number;
    ram_total_mb?: number;
  };
  services: Record<string, boolean>;
  counts: Record<string, number>;
}

export function System() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [an, setAn] = useState<any>(null);

  useEffect(() => {
    const load = () => {
      api.get<Stats>("/system/stats").then(setStats).catch(() => setStats(null));
      api.get<any>("/system/analytics").then(setAn).catch(() => setAn(null));
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <Activity size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">System</h1>
      </div>

      {!stats && <div className="text-sm text-muted">Loading…</div>}

      {stats && (
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-line bg-panel p-4">
            <div className="kai-metadata mb-3 uppercase">Resources</div>
            <div className="space-y-1 font-mono text-sm">
              <div>CPU {stats.resources.cpu_percent ?? "—"}%</div>
              <div>Cores {stats.resources.cpu_process_cores ?? "—"} / {stats.resources.cpu_cores ?? "—"}</div>
              <div className="kai-metadata">Threads {stats.resources.cpu_process_threads ?? "—"}</div>
              <div>RAM {stats.resources.ram_percent ?? "—"}%</div>
              <div className="kai-metadata">
                {stats.resources.ram_used_mb ?? "—"} / {stats.resources.ram_total_mb ?? "—"} MB
              </div>
            </div>
          </div>
          <div className="rounded-lg border border-line bg-panel p-4">
            <div className="kai-metadata mb-3 uppercase">Services</div>
            <div className="space-y-1 text-sm">
              {Object.entries(stats.services).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span>{k}</span>
                  <span style={{ color: v ? "var(--kai-verified)" : "var(--kai-accent)" }}>
                    ● {v ? "up" : "down"}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-line bg-panel p-4">
            <div className="kai-metadata mb-3 uppercase">Index counts</div>
            <div className="space-y-1 font-mono text-sm">
              {Object.entries(stats.counts).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="kai-metadata uppercase">{k}</span>
                  <span>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {an && an.available && (
        <div className="mt-6">
          <div className="kai-metadata mb-3 uppercase">Public usage analytics</div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {[
              ["Visitors", an.unique_visitors],
              ["Visitors today", an.unique_visitors_today],
              ["Total events", an.total_events],
              ["Events today", an.events_today],
            ].map(([label, val]) => (
              <div key={label as string} className="rounded-lg border border-line bg-panel p-4">
                <div className="kai-metadata uppercase">{label}</div>
                <div className="mt-2 font-mono text-2xl font-semibold">{(val as number)?.toLocaleString?.() ?? 0}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border border-line bg-panel p-4">
              <div className="kai-metadata mb-3 uppercase">By feature</div>
              <div className="space-y-1 font-mono text-sm">
                {Object.entries(an.by_event || {}).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between">
                    <span className="kai-metadata uppercase">{k.replace("public_", "")}</span>
                    <span>{v as number}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-line bg-panel p-4">
              <div className="kai-metadata mb-3 uppercase">Last 7 days</div>
              <div className="flex items-end gap-1" style={{ height: 90 }}>
                {(an.series || []).map((d: any) => {
                  const max = Math.max(1, ...(an.series || []).map((s: any) => s.events));
                  return (
                    <div key={d.day} className="flex flex-1 flex-col items-center justify-end gap-1" title={`${d.day}: ${d.events} events, ${d.visitors} visitors`}>
                      <div className="w-full" style={{ height: `${Math.round((d.events / max) * 70)}px`, background: "var(--kai-accent)", minHeight: d.events ? 3 : 0 }} />
                      <span className="kai-metadata" style={{ fontSize: 9 }}>{d.day.slice(6)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="mt-4 rounded-lg border border-line bg-panel p-4">
            <div className="kai-metadata mb-3 uppercase">Recent public activity</div>
            {(!an.recent || an.recent.length === 0) ? (
              <div className="text-sm text-muted">No public activity yet.</div>
            ) : (
              <div className="max-h-64 space-y-1 overflow-auto font-mono text-xs">
                {an.recent.map((r: any, i: number) => (
                  <div key={i} className="flex items-center justify-between border-b border-line/50 py-1">
                    <span className="uppercase text-muted">{String(r.event).replace("public_", "")}</span>
                    <span className="text-muted">visitor {String(r.ip).slice(0, 8)} · {new Date(r.at * 1000).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="kai-metadata mt-3 border-t border-line pt-2">Visitor IDs are salted hashes — raw IPs are never stored.</div>
          </div>
        </div>
      )}
    </div>
  );
}
