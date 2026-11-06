import { useEffect, useState } from "react";
import { Zap, KeyRound, Save, Cpu, BookOpen, Trash2, Terminal, AlertTriangle, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api";
import { toolsApi, type ToolDoc, type Capabilities } from "@/lib/tools";
import { Markdown } from "@/components/Markdown";

interface ModelStatus {
  model: string; reachable: boolean; model_installed: boolean; ready: boolean; error: string | null;
  backend?: "ollama" | "llamacpp"; accelerator?: string | null;
}

const BACKENDS: { id: "llamacpp" | "ollama"; label: string; hint: string }[] = [
  { id: "llamacpp", label: "llama.cpp", hint: "llama-server · GPU offload (Vulkan / CUDA)" },
  { id: "ollama", label: "Ollama", hint: "Ollama server" },
];

function ChatModelSelector() {
  const [models, setModels] = useState<string[]>([]);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [choice, setChoice] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  function load() {
    api.get<{ models: string[]; configured: string }>("/chat/models")
      .then((r) => { setModels(r.models); setChoice((c) => c || r.configured); })
      .catch(() => setModels([]));
    api.get<ModelStatus>("/chat/status").then((s) => { setStatus(s); setChoice((c) => c || s.model); }).catch(() => setStatus(null));
  }
  useEffect(load, []);

  async function switchBackend(id: "llamacpp" | "ollama") {
    setSaving(true); setMsg(null);
    try {
      await api.post("/settings/keys", { values: { kai_llm_backend: id } });
      setMsg(`Chat now runs on ${id === "llamacpp" ? "llama.cpp" : "Ollama"}. New chats use it immediately.`);
      setChoice("");
      load();
    } catch {
      setMsg("Failed to switch backend.");
    } finally {
      setSaving(false);
    }
  }

  async function save() {
    if (!choice) return;
    setSaving(true); setMsg(null);
    try {
      await api.post("/settings/keys", { values: { kai_ollama_model: choice } });
      setMsg(`Now using ${choice}. New chats use it immediately.`);
      load();
    } catch {
      setMsg("Failed to switch model.");
    } finally {
      setSaving(false);
    }
  }

  // ensure the configured model is always selectable even if not in the list
  const options = Array.from(new Set([choice, ...(status ? [status.model] : []), ...models].filter(Boolean)));
  const dirty = status != null && choice !== status.model;
  const color = status?.ready ? "var(--kai-verified)" : "var(--kai-accent)";

  return (
    <div className="hud-panel hud-frame mb-6 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Cpu size={16} style={{ color: "var(--kai-hud)" }} />
        <span className="hud-mono uppercase text-xs" style={{ color: "var(--kai-hud)" }}>◢ KAI chat model</span>
        {status && (
          <span className="kai-metadata" style={{ color }}>
            ● {status.ready ? `${status.model} ready` : status.reachable ? (status.error || `${status.model} not installed`) : `${status.backend === "llamacpp" ? "llama.cpp" : "Ollama"} offline`}
            {status.ready && status.accelerator ? ` · ${status.accelerator}` : ""}
          </span>
        )}
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {BACKENDS.map((b) => {
          const on = (status?.backend ?? "ollama") === b.id;
          return (
            <button key={b.id} onClick={() => !on && switchBackend(b.id)} disabled={saving} title={b.hint}
              className={`rounded-md border px-3 py-1.5 text-xs disabled:opacity-40 ${on ? "" : "border-line text-muted hover:bg-panel-2"}`}
              style={on ? { borderColor: "var(--kai-hud)", color: "var(--kai-hud)" } : undefined}>
              {on ? "● " : ""}{b.label}
            </button>
          );
        })}
      </div>
      {status?.backend === "llamacpp" ? (
        <div className="kai-metadata text-muted">
          llama.cpp serves one model, chosen when its server starts (<span className="font-mono">kai-llama</span> service).
          Serving <span className="font-mono">{status.model}</span>.
        </div>
      ) : (
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          className="min-w-56 rounded-md border border-line bg-panel-2 px-3 py-2 font-mono text-xs outline-none focus:border-muted"
        >
          {options.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <button
          onClick={save}
          disabled={saving || !dirty}
          className="flex items-center gap-1 rounded-md border border-line px-3 py-2 text-xs hover:bg-panel-2 disabled:opacity-40"
        >
          <Save size={13} /> {saving ? "Switching…" : "Use model"}
        </button>
        <button onClick={load} className="rounded-md border border-line px-2 py-2 text-xs hover:bg-panel-2">refresh</button>
      </div>
      )}
      {msg && <div className="mt-2 kai-metadata" style={{ color: "var(--kai-verified)" }}>{msg}</div>}
      <div className="kai-metadata mt-2 text-muted">
        Pick the inference engine. Switching writes KAI_LLM_BACKEND to the backend .env and hot-reloads —
        KAI never silently falls back to a different engine or a cloud model.
      </div>
    </div>
  );
}

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

function ToolDocsManager() {
  const [docs, setDocs] = useState<ToolDoc[]>([]);
  const [mode, setMode] = useState<"url" | "text" | "file">("url");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [toolName, setToolName] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [viewing, setViewing] = useState<ToolDoc | null>(null);

  function load() {
    toolsApi.docs().then(setDocs).catch(() => setDocs([]));
  }
  useEffect(load, []);

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setFileName(f.name);
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result ?? ""));
    reader.readAsText(f);
  }

  async function add() {
    setBusy(true);
    setMsg(null);
    try {
      if (mode === "url") {
        if (!url.trim()) throw new Error("Enter a URL");
        await toolsApi.addDoc({ source_type: "url", url: url.trim(),
          tool_name: toolName.trim() || undefined, title: title.trim() || undefined });
      } else {
        if (!text.trim()) throw new Error(mode === "file" ? "Choose a readable text file" : "Paste some text");
        await toolsApi.addDoc({ source_type: mode, content: text,
          source_ref: mode === "file" ? fileName : undefined,
          tool_name: toolName.trim() || undefined, title: title.trim() || undefined });
      }
      setUrl(""); setText(""); setFileName(""); setToolName(""); setTitle("");
      setMsg("Added — KAI will read it as reference on the next turn.");
      load();
    } catch (e: any) {
      setMsg(e?.message || "Failed to add documentation");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    await toolsApi.deleteDoc(id).catch(() => null);
    if (viewing?.id === id) setViewing(null);
    load();
  }

  async function view(id: string) {
    try { setViewing(await toolsApi.getDoc(id)); } catch { /* */ }
  }

  const inputCls = "w-full rounded border border-line bg-panel-2 px-2 py-1 text-sm outline-none focus:border-current";

  return (
    <div className="hud-panel hud-frame mb-8 p-4">
      <div className="mb-3 flex items-center gap-2">
        <BookOpen size={16} style={{ color: "var(--kai-hud)" }} />
        <h2 className="hud-mono text-sm font-semibold" style={{ color: "var(--kai-hud)" }}>Tool Documentation</h2>
      </div>
      <p className="mb-3 max-w-2xl text-xs text-muted">
        Add docs for a tool (scrape a URL, upload a text file, or paste text). KAI reads them as
        read-only reference so it understands how the tool works. This is context, not training —
        doc content is treated as untrusted data, never as commands.
      </p>

      <div className="mb-2 flex gap-1 text-xs">
        {(["url", "file", "text"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)}
            className="rounded border border-line px-2 py-0.5"
            style={m === mode ? { color: "var(--kai-hud)", borderColor: "var(--kai-hud)" } : { color: "var(--kai-muted)" }}>
            {m === "url" ? "from URL" : m === "file" ? "from file" : "paste text"}
          </button>
        ))}
      </div>

      <div className="grid gap-2">
        {mode === "url" && (
          <input className={inputCls} placeholder="https://… (documentation page)"
            value={url} onChange={(e) => setUrl(e.target.value)} />
        )}
        {mode === "file" && (
          <input type="file" accept=".txt,.md,.rst,.json,.html,.htm,.1,text/*" onChange={onFile}
            className="text-xs text-muted" />
        )}
        {mode === "text" && (
          <textarea className={inputCls} rows={4} placeholder="Paste documentation text…"
            value={text} onChange={(e) => setText(e.target.value)} />
        )}
        <div className="flex gap-2">
          <input className={inputCls} placeholder="tool name (optional, e.g. nmap)"
            value={toolName} onChange={(e) => setToolName(e.target.value)} />
          <input className={inputCls} placeholder="title (optional)"
            value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="flex items-center gap-3">
          <button onClick={add} disabled={busy}
            className="rounded border border-line px-3 py-1 text-sm hover:bg-panel-2"
            style={{ color: "var(--kai-verified)" }}>
            {busy ? "Adding…" : "Add doc"}
          </button>
          {msg && <span className="text-xs text-muted">{msg}</span>}
        </div>
      </div>

      <div className="mt-4 grid gap-1">
        {docs.map((d) => (
          <div key={d.id} className="flex items-center justify-between rounded border border-line px-2 py-1 text-xs">
            <button onClick={() => view(d.id)} className="truncate text-left hover:underline" title={d.title}>
              <span style={{ color: "var(--kai-hud)" }}>{d.title}</span>
              {d.tool_name && <span className="text-muted"> · {d.tool_name}</span>}
              <span className="text-muted"> · {d.source_type} · {d.char_count.toLocaleString()} chars</span>
            </button>
            <button onClick={() => remove(d.id)} className="ml-2 text-muted hover:text-current" title="Delete">
              <Trash2 size={13} />
            </button>
          </div>
        ))}
        {docs.length === 0 && <div className="kai-metadata text-muted">No tool docs yet.</div>}
      </div>

      {viewing && (
        <div className="mt-3 rounded border border-line p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="hud-mono text-sm" style={{ color: "var(--kai-hud)" }}>{viewing.title}</span>
            <button onClick={() => setViewing(null)} className="text-xs text-muted hover:text-current">close</button>
          </div>
          {viewing.source_ref && <div className="kai-metadata mb-2 break-all text-muted">{viewing.source_ref}</div>}
          <div className="max-h-80 overflow-auto text-sm">
            <Markdown>{viewing.content_text ?? ""}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

function CapabilitiesPanel() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    toolsApi.capabilities().then(setCaps).catch(() => setErr("Could not load capabilities."));
  }, []);

  async function patch(change: Partial<Capabilities>, key: string) {
    setSaving(key);
    setErr(null);
    try {
      setCaps(await toolsApi.setCapabilities(change));
    } catch {
      setErr("Failed to update.");
    } finally {
      setSaving(null);
    }
  }

  const Toggle = ({ on, busy, onClick }: { on: boolean; busy: boolean; onClick: () => void }) => (
    <button
      onClick={onClick}
      disabled={busy}
      className="rounded border border-line px-3 py-1 text-xs hover:bg-panel-2 disabled:opacity-40"
      style={{ color: on ? "var(--kai-verified)" : "var(--kai-muted)" }}
    >
      {busy ? "…" : on ? "ON" : "OFF"}
    </button>
  );

  return (
    <div className="hud-panel hud-frame mb-8 p-4">
      <div className="mb-3 flex items-center gap-2">
        <ShieldCheck size={16} style={{ color: "var(--kai-hud)" }} />
        <span className="hud-mono uppercase text-xs" style={{ color: "var(--kai-hud)" }}>◢ KAI capabilities — what the model may do</span>
      </div>
      <p className="mb-4 max-w-2xl text-sm text-muted">
        Permissions for the KAI agent. Every tool and command runs through the
        backend gate and is logged in Execution History regardless of these switches.
      </p>

      {err && <div className="mb-2 kai-metadata" style={{ color: "var(--kai-accent)" }}>{err}</div>}
      {!caps && !err && <div className="kai-metadata text-muted">Loading…</div>}

      {caps && (
        <div className="grid gap-3">
          {/* installed tools */}
          <div className="flex items-start justify-between gap-4 rounded border border-line p-3">
            <div className="flex items-start gap-2">
              <Cpu size={15} className="mt-0.5" style={{ color: "var(--kai-hud)" }} />
              <div>
                <div className="text-sm">Installed tools (catalogue)</div>
                <div className="kai-metadata text-muted">
                  Let KAI run installed OSINT/recon/security tools (nmap, msf search, etc.),
                  authorized and argv-only.
                </div>
              </div>
            </div>
            <Toggle on={caps.tools_enabled} busy={saving === "tools"}
              onClick={() => patch({ tools_enabled: !caps.tools_enabled }, "tools")} />
          </div>

          {/* terminal */}
          <div className="rounded border p-3"
            style={{ borderColor: caps.shell_enabled ? "var(--kai-warn)" : "var(--kai-line)" }}>
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-2">
                <Terminal size={15} className="mt-0.5" style={{ color: "var(--kai-hud)" }} />
                <div>
                  <div className="text-sm">Terminal access (raw shell)</div>
                  <div className="kai-metadata text-muted">
                    Let KAI run arbitrary shell commands on this host via <span className="font-mono">bash -lc</span>,
                    with your real environment. Off by default.
                  </div>
                </div>
              </div>
              <Toggle on={caps.shell_enabled} busy={saving === "shell"}
                onClick={() => patch({ shell_enabled: !caps.shell_enabled }, "shell")} />
            </div>

            {caps.shell_enabled && (
              <div className="mt-3 border-t border-line pt-3">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-2">
                    <AlertTriangle size={15} className="mt-0.5" style={{ color: "var(--kai-warn)" }} />
                    <div>
                      <div className="text-sm">Auto-run commands (no approval)</div>
                      <div className="kai-metadata text-muted">
                        When ON, KAI runs shell commands with no per-command prompt.
                        When OFF, every command waits for you to approve it in chat.
                      </div>
                    </div>
                  </div>
                  <Toggle on={caps.shell_auto_run} busy={saving === "auto"}
                    onClick={() => patch({ shell_auto_run: !caps.shell_auto_run }, "auto")} />
                </div>

                <div className="mt-3 flex items-start justify-between gap-4 border-t border-line pt-3">
                  <div className="flex items-start gap-2">
                    <ShieldCheck size={15} className="mt-0.5" style={{ color: "var(--kai-warn)" }} />
                    <div>
                      <div className="text-sm">Root commands (sudo)</div>
                      <div className="kai-metadata text-muted">
                        Let KAI run commands as root. It runs via <span className="font-mono">pkexec</span>,
                        so your desktop asks for your password each time — even in auto-run.
                      </div>
                    </div>
                  </div>
                  <Toggle on={caps.shell_sudo} busy={saving === "sudo"}
                    onClick={() => patch({ shell_sudo: !caps.shell_sudo }, "sudo")} />
                </div>

                <div className="mt-3 rounded p-2 text-xs"
                  style={{ background: "color-mix(in srgb, var(--kai-warn) 12%, transparent)", color: "var(--kai-warn)" }}>
                  ⚠ Terminal access lets the model run anything your user can. If this
                  machine is reachable over a public tunnel with login disabled, anyone
                  who finds it gets a shell on your PC — especially with auto-run ON. Keep
                  the tunnel private or turn open-access off.
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
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

      <ChatModelSelector />

      <CapabilitiesPanel />

      <ToolDocsManager />

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
