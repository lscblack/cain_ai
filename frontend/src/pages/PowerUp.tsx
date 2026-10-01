import { useEffect, useState } from "react";
import { Zap } from "lucide-react";

import { api } from "@/lib/api";

interface Provider {
  name: string;
  type: string;
  enabled: boolean;
  operator_disabled: boolean;
  configured: boolean;
  healthy: boolean;
  detail: string | null;
}

export function PowerUp() {
  const [providers, setProviders] = useState<Provider[]>([]);

  function load() {
    api.get<{ providers: Provider[] }>("/powerup/providers")
      .then((r) => setProviders(r.providers))
      .catch(() => setProviders([]));
  }

  useEffect(() => {
    load();
  }, []);

  async function toggle(name: string, enabled: boolean) {
    await api.post(`/powerup/providers/${name}/toggle`, { enabled }).catch(() => null);
    load();
  }

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <Zap size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Power Up — Providers</h1>
      </div>
      <p className="mb-5 max-w-2xl text-sm text-muted">
        Intelligence providers KAI can use. Local providers run offline. External
        providers require an API key in the backend <span className="font-mono">.env</span> and
        report <span className="font-mono">UNAVAILABLE</span> until configured. Secrets never reach this UI.
      </p>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {providers.map((p) => {
          const color = p.healthy ? "var(--kai-verified)" : "var(--kai-accent)";
          return (
            <div key={p.name} className="rounded-lg border border-line bg-panel p-4">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm">{p.name}</span>
                <span className="kai-metadata uppercase" style={{ color }}>
                  ● {p.healthy ? "connected" : "unavailable"}
                </span>
              </div>
              <div className="kai-metadata mt-2 uppercase">{p.type.replace(/_/g, " ")}</div>
              <div className="mt-3 flex items-center justify-between kai-metadata">
                <span>{p.configured ? "configured" : "no key"}</span>
                <button
                  onClick={() => toggle(p.name, p.operator_disabled)}
                  className="rounded border border-line px-2 py-0.5 hover:bg-panel-2"
                  style={{ color: p.operator_disabled ? "var(--kai-muted)" : "var(--kai-verified)" }}
                >
                  {p.operator_disabled ? "disabled → enable" : "enabled → disable"}
                </button>
              </div>
              {p.detail && <div className="kai-metadata mt-2 text-muted">{p.detail}</div>}
            </div>
          );
        })}
        {providers.length === 0 && <div className="text-sm text-muted">No providers registered.</div>}
      </div>
    </div>
  );
}
