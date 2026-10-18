import { useCallback, useEffect, useState } from "react";
import {
  ShieldCheck, Package, History, Crosshair, AlertTriangle, Play, Trash2, RefreshCw,
} from "lucide-react";

import {
  toolsApi, type Inventory, type Execution, type Target, type InstallReq, type ToolOperation,
} from "@/lib/tools";
import type { Finding } from "@/lib/chat";

const TABS = ["Inventory", "Installs", "Executions", "Targets", "Findings"] as const;
type Tab = (typeof TABS)[number];

const POSTURE_COLOR: Record<string, string> = {
  passive: "var(--kai-hud)", active: "#f59e0b", disruptive: "var(--kai-accent)",
};

function Panel({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="hud-panel hud-frame p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="hud-mono uppercase text-xs" style={{ color: "var(--kai-hud)" }}>◢ {title}</div>
        {right}
      </div>
      {children}
    </div>
  );
}

function RunOp({ op, onDone }: { op: ToolOperation; onDone: () => void }) {
  const [params, setParams] = useState<Record<string, any>>(
    Object.fromEntries(op.params.map((p) => [p.name, p.default ?? ""])),
  );
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try { setResult(await toolsApi.execute(op.key, params)); } catch (e: any) { setResult({ status: "error", error: e?.message }); }
    setBusy(false);
    onDone();
  }
  return (
    <div className="mt-2 rounded border border-line bg-panel-2 p-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        {op.params.map((p) => (
          <input key={p.name} placeholder={`${p.name}${p.required ? "*" : ""}`} value={params[p.name] ?? ""}
            onChange={(e) => setParams((s) => ({ ...s, [p.name]: e.target.value }))}
            title={p.help}
            className="w-32 rounded border border-line bg-panel px-2 py-1 outline-none focus:border-current" />
        ))}
        <button onClick={run} disabled={busy}
          className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel disabled:opacity-40">
          <Play size={12} /> {busy ? "running…" : "run"}
        </button>
      </div>
      {result && (
        <div className="mt-2">
          <div className="hud-mono" style={{ color: result.ok ? "var(--kai-verified)" : "var(--kai-accent)" }}>
            ● {result.status}{result.exit_code != null ? ` · exit ${result.exit_code}` : ""}{result.duration_ms != null ? ` · ${result.duration_ms}ms` : ""}
          </div>
          {(result.message || result.error) && <div className="text-muted">{result.message || result.error}</div>}
          {(result.stdout || result.stderr) && (
            <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-muted">
              {(result.stdout || "") + (result.stderr ? "\n" + result.stderr : "")}
            </pre>
          )}
          {result.result && <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-muted">{JSON.stringify(result.result, null, 2)}</pre>}
        </div>
      )}
    </div>
  );
}

export function Security() {
  const [tab, setTab] = useState<Tab>("Inventory");
  const [inv, setInv] = useState<Inventory | null>(null);
  const [execs, setExecs] = useState<Execution[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [installs, setInstalls] = useState<InstallReq[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [newTarget, setNewTarget] = useState({ target: "", scope: "active", note: "" });
  const [newInstall, setNewInstall] = useState({ package: "", reason: "" });
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setInv(await toolsApi.inventory()); } catch { /* */ }
    try { setExecs(await toolsApi.executions()); } catch { /* */ }
    try { setTargets(await toolsApi.targets()); } catch { /* */ }
    try { setFindings(await toolsApi.findings()); } catch { /* */ }
    try { setInstalls(await toolsApi.installRequests()); } catch { /* */ }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function addTarget() {
    if (!newTarget.target.trim()) return;
    try {
      await toolsApi.addTarget(newTarget.target.trim(), newTarget.scope, newTarget.note);
      setNewTarget({ target: "", scope: "active", note: "" });
      setTargets(await toolsApi.targets());
    } catch (e: any) { setMsg(e?.message || "failed"); }
  }
  async function requestInstall() {
    if (!newInstall.package.trim()) return;
    try {
      await toolsApi.requestInstall({ package: newInstall.package.trim(), reason: newInstall.reason });
      setNewInstall({ package: "", reason: "" });
      setInstalls(await toolsApi.installRequests());
    } catch (e: any) { setMsg(e?.message || "failed"); }
  }
  async function approve(id: string) {
    setMsg("installing…");
    try {
      const r = await toolsApi.approveInstall(id);
      setMsg(`${r.request.status}${r.outcome?.sudo_needs_password ? " — sudo needs a password (configure a scoped NOPASSWD rule)" : ""}`);
    } catch (e: any) { setMsg(e?.message || "failed"); }
    setInstalls(await toolsApi.installRequests());
    setInv(await toolsApi.inventory());
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <ShieldCheck size={18} style={{ color: "var(--kai-hud)" }} />
        <h1 className="hud-mono hud-glow text-lg font-semibold" style={{ color: "var(--kai-hud)" }}>◢ Security Console</h1>
        <button onClick={refresh} className="ml-2 flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel">
          <RefreshCw size={12} /> refresh
        </button>
      </div>

      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex items-center gap-1 border-b-2 px-3 py-2 hud-mono text-xs ${tab === t ? "" : "border-transparent text-muted"}`}
            style={tab === t ? { color: "var(--kai-hud)", borderColor: "var(--kai-hud)" } : undefined}>
            {t === "Inventory" && <Package size={13} />}
            {t === "Installs" && <Package size={13} />}
            {t === "Executions" && <History size={13} />}
            {t === "Targets" && <Crosshair size={13} />}
            {t === "Findings" && <AlertTriangle size={13} />}
            {t}
            {t === "Inventory" && inv ? ` (${inv.counts.installed}/${inv.counts.total})` : ""}
          </button>
        ))}
      </div>

      {msg && <div className="mb-3 text-xs text-muted">{msg}</div>}

      {tab === "Inventory" && inv && (
        <div className="grid gap-3 md:grid-cols-2">
          {inv.tools.map((t) => (
            <Panel key={t.name} title={t.name}
              right={<span className="hud-mono text-xs" style={{ color: t.installed ? "var(--kai-verified)" : "var(--kai-accent)" }}>
                ● {t.installed ? (t.version || "installed") : "not installed"}</span>}>
              <div className="text-sm text-muted">{t.purpose}</div>
              <div className="kai-metadata mt-1">pkg: {t.package || "(builtin)"} · {t.source} · {t.path || "—"}</div>
              <div className="mt-2 space-y-2">
                {t.operations.map((op) => (
                  <div key={op.key} className="border-t border-line/50 pt-2">
                    <button className="flex w-full items-center justify-between text-left text-xs"
                      onClick={() => setExpanded(expanded === op.key ? null : op.key)}>
                      <span><span style={{ color: "var(--kai-hud)" }}>{op.key}</span> <span className="text-muted">— {op.title}</span></span>
                      <span className="hud-mono uppercase" style={{ color: POSTURE_COLOR[op.posture] }}>
                        {op.posture}{op.requires_authorization ? " · auth" : ""}
                      </span>
                    </button>
                    {expanded === op.key && (t.installed
                      ? <RunOp op={op} onDone={refresh} />
                      : <div className="kai-metadata mt-1">Install “{t.package}” first (Installs tab).</div>)}
                  </div>
                ))}
              </div>
            </Panel>
          ))}
        </div>
      )}

      {tab === "Installs" && (
        <div className="space-y-3">
          <Panel title="Request a package install">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <input placeholder="package (e.g. sslscan)" value={newInstall.package}
                onChange={(e) => setNewInstall((s) => ({ ...s, package: e.target.value }))}
                className="w-48 rounded border border-line bg-panel-2 px-2 py-1 outline-none focus:border-current" />
              <input placeholder="reason" value={newInstall.reason}
                onChange={(e) => setNewInstall((s) => ({ ...s, reason: e.target.value }))}
                className="w-64 rounded border border-line bg-panel-2 px-2 py-1 outline-none focus:border-current" />
              <button onClick={requestInstall} className="rounded border border-line px-2 py-1 hover:bg-panel">request</button>
            </div>
            <div className="kai-metadata mt-2">
              Installs run apt through a scoped privileged helper after you approve. The model can request; only you approve.
            </div>
          </Panel>
          {installs.map((r) => (
            <Panel key={r.id} title={r.package}
              right={<span className="hud-mono text-xs" style={{
                color: r.status === "installed" ? "var(--kai-verified)" : r.status === "failed" || r.status === "rejected" ? "var(--kai-accent)" : "#f59e0b" }}>
                ● {r.status}{r.installed_version ? ` · ${r.installed_version}` : ""}</span>}>
              <div className="text-sm text-muted">{r.reason || "—"}</div>
              <div className="kai-metadata mt-1">source: {r.source} · root: {String(r.needs_root)}</div>
              {r.status === "pending" && (
                <div className="mt-2 flex gap-2 text-xs">
                  <button onClick={() => approve(r.id)} className="rounded border border-line px-2 py-1 hover:bg-panel" style={{ color: "var(--kai-verified)" }}>approve &amp; install</button>
                  <button onClick={async () => { await toolsApi.rejectInstall(r.id); setInstalls(await toolsApi.installRequests()); }}
                    className="rounded border border-line px-2 py-1 hover:bg-panel" style={{ color: "var(--kai-accent)" }}>reject</button>
                </div>
              )}
              {r.log && <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-muted">{r.log}</pre>}
            </Panel>
          ))}
          {installs.length === 0 && <div className="kai-metadata">No install requests yet.</div>}
        </div>
      )}

      {tab === "Executions" && (
        <div className="space-y-2">
          {execs.map((e) => (
            <div key={e.id} className="hud-panel rounded border border-line p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="hud-mono" style={{ color: "var(--kai-hud)" }}>{e.operation}</span>
                <span className="hud-mono" style={{ color: e.status === "ok" ? "var(--kai-verified)" : "var(--kai-accent)" }}>● {e.status}</span>
                {e.posture && <span className="kai-metadata uppercase">{e.posture}</span>}
                {e.target && <span className="kai-metadata">target: {e.target}</span>}
                {e.duration_ms != null && <span className="kai-metadata">{e.duration_ms}ms</span>}
                <span className="kai-metadata ml-auto">{e.created_at ? new Date(e.created_at).toLocaleString() : ""}</span>
              </div>
              <div className="kai-metadata mt-1">{(e.args || []).join("  ")}</div>
              {(e.stdout || e.stderr || e.error) && (
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-muted">
                  {(e.stdout || "") + (e.stderr ? "\n" + e.stderr : "") + (e.error ? "\n" + e.error : "")}
                </pre>
              )}
            </div>
          ))}
          {execs.length === 0 && <div className="kai-metadata">No tool executions yet.</div>}
        </div>
      )}

      {tab === "Targets" && (
        <div className="space-y-3">
          <Panel title="Authorize a target for active assessment">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <input placeholder="host / IP / CIDR" value={newTarget.target}
                onChange={(e) => setNewTarget((s) => ({ ...s, target: e.target.value }))}
                className="w-48 rounded border border-line bg-panel-2 px-2 py-1 outline-none focus:border-current" />
              <select value={newTarget.scope} onChange={(e) => setNewTarget((s) => ({ ...s, scope: e.target.value }))}
                className="rounded border border-line bg-panel-2 px-2 py-1">
                <option value="active">active</option><option value="passive">passive</option>
              </select>
              <input placeholder="note" value={newTarget.note}
                onChange={(e) => setNewTarget((s) => ({ ...s, note: e.target.value }))}
                className="w-48 rounded border border-line bg-panel-2 px-2 py-1 outline-none focus:border-current" />
              <button onClick={addTarget} className="rounded border border-line px-2 py-1 hover:bg-panel">authorize</button>
            </div>
            <div className="kai-metadata mt-2">Active scans (e.g. nmap) are refused unless the target is listed here. Only authorize assets you own or are permitted to test.</div>
          </Panel>
          <div className="space-y-1">
            {targets.map((t) => (
              <div key={t.id} className="flex items-center justify-between rounded border border-line bg-panel-2 px-3 py-2 text-sm">
                <span><span style={{ color: "var(--kai-hud)" }}>{t.target}</span> <span className="kai-metadata">· {t.scope}{t.note ? ` · ${t.note}` : ""}</span></span>
                <button onClick={async () => { await toolsApi.removeTarget(t.id); setTargets(await toolsApi.targets()); }}><Trash2 size={13} className="text-muted hover:text-ink" /></button>
              </div>
            ))}
            {targets.length === 0 && <div className="kai-metadata">No authorized targets.</div>}
          </div>
        </div>
      )}

      {tab === "Findings" && (
        <div className="space-y-2">
          {findings.map((f, i) => (
            <div key={f.id || i} className="hud-panel rounded border-l-2 p-3 text-xs"
              style={{ borderColor: f.severity === "high" || f.severity === "critical" ? "var(--kai-accent)" : "var(--kai-hud)" }}>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-ink">{f.title}</span>
                <span className="hud-mono uppercase">{f.severity}</span>
                <span className="kai-metadata">· {f.confidence} · {f.status}{f.tool ? ` · ${f.tool}` : ""}</span>
              </div>
              {f.asset && <div className="kai-metadata mt-1">asset: {f.asset}</div>}
              {f.description && <div className="mt-1 text-muted">{f.description}</div>}
              {f.remediation && <div className="mt-1"><span className="kai-metadata">remediation:</span> {f.remediation}</div>}
            </div>
          ))}
          {findings.length === 0 && <div className="kai-metadata">No findings recorded yet.</div>}
        </div>
      )}
    </div>
  );
}
