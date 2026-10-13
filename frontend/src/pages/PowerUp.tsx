import { useEffect, useState } from "react";
import { Zap, KeyRound, Save } from "lucide-react";

import { api } from "@/lib/api";

interface ManagedKey {
  field: string;
  env: string;
  label: string;
  secret: boolean;
  configured: boolean;
  masked: string | null;
}

function KeysEditor({ onSaved }: { onSaved: () => void }) {
  const [keys, setKeys] = useState<ManagedKey[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  function load() {
    api.get<{ keys: ManagedKey[] }>("/settings/keys").then((r) => setKeys(r.keys)).catch(() => setKeys([]));
  }
  useEffect(load, []);

  async function save() {
    const values = Object.fromEntries(Object.entries(edits).filter(([, v]) => v.trim() !== ""));
    if (Object.keys(values).length === 0) return;
    setSaving(true);
    setMsg(null);
    try {
      await api.post("/settings/keys", { values });
      setEdits({});
      setMsg("Saved to .env and reloaded.");
      load();
      onSaved();
    } catch {
      setMsg("Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="hud-panel hud-frame mb-8 p-4">
      <div className="mb-3 flex items-center gap-2">
        <KeyRound size={16} style={{ color: "var(--kai-hud)" }} />
        <span className="hud-mono uppercase text-xs" style={{ color: "var(--kai-hud)" }}>◢ Provider keys</span>
        <span className="kai-metadata text-muted">— saved to backend .env, never shown back</span>
        <button
          onClick={save}
          disabled={saving || Object.keys(edits).length === 0}
          className="ml-auto flex items-center gap-1 rounded-md border border-line px-3 py-1.5 text-xs hover:bg-panel-2 disabled:opacity-40"
        >
          <Save size={13} /> {saving ? "Saving…" : "Save keys"}
        </button>
      </div>
      {msg && <div className="mb-2 kai-metadata" style={{ color: "var(--kai-verified)" }}>{msg}</div>}
      <div className="grid gap-3 md:grid-cols-2">
        {keys.map((k) => (
          <label key={k.field} className="block">
            <div className="kai-metadata mb-1 flex items-center justify-between">
              <span>{k.label}</span>
              <span style={{ color: k.configured ? "var(--kai-verified)" : "var(--kai-muted)" }}>
                {k.configured ? "set" : "empty"}
              </span>
            </div>
            <input
              type={k.secret ? "password" : "text"}
              value={edits[k.field] ?? ""}
              onChange={(e) => setEdits((s) => ({ ...s, [k.field]: e.target.value }))}
              placeholder={k.configured ? (k.masked ?? "••••") : `set ${k.env}`}
              className="w-full rounded-md border border-line bg-panel-2 px-3 py-2 font-mono text-xs outline-none focus:border-muted"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

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
        <Zap size={18} style={{ color: "var(--kai-hud)" }} />
        <h1 className="hud-mono hud-glow text-lg font-semibold" style={{ color: "var(--kai-hud)" }}>◢ Power Up — Providers</h1>
      </div>
      <p className="mb-5 max-w-2xl text-sm text-muted">
        Intelligence providers KAI can use. Local providers run offline. External
        providers need an API key — add it below and it's written to the backend
        <span className="font-mono"> .env</span> and hot-reloaded. Secrets are never shown back to this UI.
      </p>

      <KeysEditor onSaved={load} />

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {providers.map((p) => {
          const color = p.healthy ? "var(--kai-verified)" : "var(--kai-accent)";
          return (
            <div key={p.name} className="hud-panel hud-frame p-4">
              <div className="flex items-center justify-between">
                <span className="hud-mono text-sm" style={{ color: "var(--kai-hud)" }}>{p.name}</span>
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
