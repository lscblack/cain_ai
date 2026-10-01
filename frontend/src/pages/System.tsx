import { useEffect, useState } from "react";
import { Activity } from "lucide-react";

import { api } from "@/lib/api";

interface Stats {
  resources: { cpu_percent?: number; ram_percent?: number; ram_used_mb?: number; ram_total_mb?: number };
  services: Record<string, boolean>;
  counts: Record<string, number>;
}

export function System() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    const load = () => api.get<Stats>("/system/stats").then(setStats).catch(() => setStats(null));
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
    </div>
  );
}
