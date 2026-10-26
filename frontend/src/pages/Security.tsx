import { useCallback, useEffect, useState } from "react";
import {
  ShieldCheck, Package, History, Crosshair, AlertTriangle, Play, Trash2, RefreshCw, Radar, Download,
} from "lucide-react";

import {
  toolsApi, type Inventory, type Execution, type Target, type InstallReq, type ToolOperation,
  type SweepResult, type InstallBatchResult,
} from "@/lib/tools";
import type { Finding } from "@/lib/chat";
import { JsonView } from "@/components/JsonView";
import { PageLoading, ErrorRetry, Spinner } from "@/components/Async";

const TABS = ["Inventory", "OSINT Sweep", "Installs", "Executions", "Targets", "Findings"] as const;
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
          {result.result && <JsonView value={result.result} />}
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
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [sweepIn, setSweepIn] = useState<Record<string, string>>(
    { domain: "", host: "", email: "", username: "", phone: "", ip: "" });
  const [sweepRes, setSweepRes] = useState<SweepResult | null>(null);
  const [sweeping, setSweeping] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [installing, setInstalling] = useState<Set<string>>(new Set());
  const [batchRes, setBatchRes] = useState<InstallBatchResult | null>(null);

  const toggleSel = (n: string) =>
    setSelected((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; });

  async function installOne(name: string, reinstall: boolean) {
    setInstalling((s) => new Set(s).add(name));
    setMsg(`${reinstall ? "reinstalling" : "installing"} ${name} — approve the system password prompt…`);
    try {
      const r = await toolsApi.installNow({ capability: name, reinstall });
      setMsg(r.verify?.installed
        ? `${name} ${reinstall ? "reinstalled" : "installed"}${r.verify.version ? ` (${r.verify.version})` : ""}`
        : `${name}: install failed${r.outcome?.error ? ` — ${r.outcome.error}` : ""}${r.outcome?.sudo_needs_password ? " — sudo needs a password" : ""}`);
    } catch (e: any) { setMsg(`${name}: ${e?.message || "install failed"}`); }
    setInstalling((s) => { const x = new Set(s); x.delete(name); return x; });
    try { setInv(await toolsApi.inventory()); setInstalls(await toolsApi.installRequests()); } catch { /* */ }
  }

  async function installMany(names: string[], reinstall: boolean) {
    if (names.length === 0) { setMsg("Nothing selected."); return; }
    if (!window.confirm(`${reinstall ? "Reinstall" : "Install"} ${names.length} tool(s) with apt? You will get one system password prompt.`)) return;
    setBatchRes(null);
    setInstalling((s) => new Set([...s, ...names]));
    setMsg(`installing ${names.length} tool(s) — approve the system password prompt…`);
    try {
      const r = await toolsApi.installBatch(names, reinstall);
      setBatchRes(r);
      setMsg(`${r.installed.length} installed · ${r.failed.length} failed · ${r.skipped.length} skipped`
        + (r.outcome?.sudo_needs_password ? " — sudo needs a password" : ""));
    } catch (e: any) { setMsg(e?.message || "batch install failed"); }
    setInstalling((s) => { const x = new Set(s); names.forEach((n) => x.delete(n)); return x; });
    setSelected(new Set());
    try { setInv(await toolsApi.inventory()); setInstalls(await toolsApi.installRequests()); } catch { /* */ }
  }

  async function runSweep() {
    const body = Object.fromEntries(Object.entries(sweepIn).filter(([, v]) => v.trim()));
    if (Object.keys(body).length === 0) { setMsg("Enter at least one identifier."); return; }
    setMsg(null); setSweeping(true); setSweepRes(null);
    try { setSweepRes(await toolsApi.sweep(body)); } catch (e: any) { setMsg(e?.message || "sweep failed"); }
    setSweeping(false);
    try { setExecs(await toolsApi.executions()); } catch { /* */ }
  }

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      // Inventory is the primary slice; if it fails we show error+retry.
      setInv(await toolsApi.inventory());
    } catch (e: any) {
      setLoadErr(e?.message || "failed to load tool inventory");
      setLoading(false);
      return;
    }
    try { setExecs(await toolsApi.executions()); } catch { /* */ }
    try { setTargets(await toolsApi.targets()); } catch { /* */ }
    try { setFindings(await toolsApi.findings()); } catch { /* */ }
    try { setInstalls(await toolsApi.installRequests()); } catch { /* */ }
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function retryExecution(e: Execution) {
    setRetrying(e.id);
    const params: Record<string, string> = {};
    for (const a of e.args || []) {
      const i = a.indexOf("=");
      if (i > 0) params[a.slice(0, i)] = a.slice(i + 1);
    }
    try { await toolsApi.execute(e.operation, params); } catch { /* recorded server-side */ }
    setRetrying(null);
    setExecs(await toolsApi.executions());
  }

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
            {t === "OSINT Sweep" && <Radar size={13} />}
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

      {loadErr && !inv && <ErrorRetry error={loadErr} onRetry={refresh} />}
      {!loadErr && loading && !inv && <PageLoading label="Loading security console…" />}

      {tab === "Inventory" && inv && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <button disabled={selected.size === 0 || installing.size > 0}
            onClick={() => installMany([...selected].filter((n) => !inv.tools.find((t) => t.name === n)?.installed), false)}
            className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel disabled:opacity-40" style={{ color: "var(--kai-verified)" }}>
            <Download size={12} /> install selected ({selected.size})
          </button>
          <button disabled={selected.size === 0 || installing.size > 0}
            onClick={() => installMany([...selected].filter((n) => inv.tools.find((t) => t.name === n)?.installed), true)}
            className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel disabled:opacity-40">
            <RefreshCw size={12} /> reinstall selected
          </button>
          <button disabled={installing.size > 0}
            onClick={() => installMany(inv.tools.filter((t) => !t.installed && t.source === "apt" && t.apt_available !== false).map((t) => t.name), false)}
            className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel disabled:opacity-40">
            <Download size={12} /> install all missing (apt)
          </button>
          <button onClick={() => setSelected(new Set(inv.tools.map((t) => t.name)))} className="text-muted hover:text-ink">select all</button>
          <button onClick={() => setSelected(new Set())} className="text-muted hover:text-ink">clear</button>
        </div>
      )}
      {tab === "Inventory" && batchRes && (
        <div className="hud-panel mb-3 rounded border border-line p-3 text-xs">
          {batchRes.installed.length > 0 && <div style={{ color: "var(--kai-verified)" }}>installed: {batchRes.installed.map((i) => i.tool).join(", ")}</div>}
          {batchRes.failed.length > 0 && <div style={{ color: "var(--kai-accent)" }}>failed: {batchRes.failed.map((i) => i.tool).join(", ")}</div>}
          {batchRes.skipped.length > 0 && <div className="text-muted">skipped: {batchRes.skipped.map((i) => `${i.tool} (${i.reason})`).join(", ")}</div>}
        </div>
      )}

      {tab === "Inventory" && inv && (
        <div className="grid gap-3 md:grid-cols-2">
          {inv.tools.map((t) => (
            <Panel key={t.name} title={t.name}
              right={<span className="flex items-center gap-2 hud-mono text-xs">
                <span style={{ color: t.installed ? "var(--kai-verified)" : "var(--kai-accent)" }}>
                  ● {t.installed ? (t.version || "installed") : "not installed"}</span>
                {t.source !== "builtin" && (
                  <input type="checkbox" checked={selected.has(t.name)} onChange={() => toggleSel(t.name)} title="select" />
                )}
              </span>}>
              <div className="text-sm text-muted">{t.purpose}</div>
              <div className="kai-metadata mt-1">pkg: {t.package || "(builtin)"} · {t.source} · {t.path || "—"}</div>
              {t.source !== "builtin" && (
                <div className="mt-2 flex items-center gap-2 text-xs">
                  {t.source === "apt" && t.apt_available === false && !t.installed ? (
                    <span className="kai-metadata">not in Ubuntu’s apt sources (Kali-only) — install manually</span>
                  ) : t.source === "apt" ? (
                    <>
                      {!t.installed && (
                        <button onClick={() => installOne(t.name, false)} disabled={installing.has(t.name)}
                          className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel disabled:opacity-40" style={{ color: "var(--kai-verified)" }}>
                          {installing.has(t.name) ? <Spinner size={12} /> : <Download size={12} />} install
                        </button>
                      )}
                      {t.installed && (
                        <button onClick={() => installOne(t.name, true)} disabled={installing.has(t.name)}
                          className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel disabled:opacity-40">
                          {installing.has(t.name) ? <Spinner size={12} /> : <RefreshCw size={12} />} reinstall
                        </button>
                      )}
                    </>
                  ) : (
                    <span className="kai-metadata">install manually ({t.source}) — not an apt package</span>
                  )}
                </div>
              )}
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
                      : <div className="kai-metadata mt-1">Not installed — use the install button above{t.source !== "apt" ? ` (${t.source}: install manually)` : ""}.</div>)}
                  </div>
                ))}
              </div>
            </Panel>
          ))}
        </div>
      )}

      {tab === "OSINT Sweep" && (
        <div className="space-y-3">
          <Panel title="Sweep identifiers with every installed tool">
            <div className="grid gap-2 sm:grid-cols-3 text-xs">
              {(["domain", "host", "email", "username", "phone", "ip"] as const).map((k) => (
                <input key={k} placeholder={k} value={sweepIn[k]}
                  onChange={(e) => setSweepIn((s) => ({ ...s, [k]: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === "Enter") runSweep(); }}
                  className="rounded border border-line bg-panel-2 px-2 py-1 outline-none focus:border-current" />
              ))}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <button onClick={runSweep} disabled={sweeping}
                className="flex items-center gap-1 rounded border border-line px-3 py-1.5 text-sm hover:bg-panel disabled:opacity-40">
                {sweeping ? <Spinner size={13} label="running tools…" /> : <><Radar size={14} /> Sweep</>}
              </button>
              {sweepRes && <span className="kai-metadata">ran {sweepRes.ran}{sweepRes.skipped ? ` · ${sweepRes.skipped} skipped` : ""}</span>}
            </div>
            <div className="kai-metadata mt-2">
              Runs all applicable INSTALLED passive tools (DNS, WHOIS, TLS, subdomains, username/email
              lookups, phone intel…) over each identifier at once. Install more tools in the Inventory tab
              to widen coverage. This is the same engine KAI uses during a person search.
            </div>
          </Panel>
          {sweepRes && sweepRes.results.map((r, i) => (
            <div key={i} className="hud-panel rounded border border-line p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="hud-mono" style={{ color: "var(--kai-hud)" }}>{r.operation}</span>
                <span className="hud-mono" style={{ color: r.ok ? "var(--kai-verified)" : "var(--kai-accent)" }}>● {r.status}</span>
                <span className="kai-metadata">{r.kind}: {r.identifier}</span>
              </div>
              {r.summary && (
                <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-muted">{r.summary}</pre>
              )}
            </div>
          ))}
          {sweepRes && sweepRes.results.length === 0 && (
            <div className="kai-metadata">No installed tools matched those identifiers — install some in the Inventory tab.</div>
          )}
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
              {(r.status === "pending" || r.status === "failed") && (
                <div className="mt-2 flex items-center gap-2 text-xs">
                  <button onClick={() => approve(r.id)} className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel" style={{ color: "var(--kai-verified)" }}>
                    {r.status === "failed" ? <><RefreshCw size={12} /> retry install</> : "approve & install"}
                  </button>
                  {r.status === "pending" && (
                    <button onClick={async () => { await toolsApi.rejectInstall(r.id); setInstalls(await toolsApi.installRequests()); }}
                      className="rounded border border-line px-2 py-1 hover:bg-panel" style={{ color: "var(--kai-accent)" }}>reject</button>
                  )}
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
                {e.status !== "ok" && e.args && e.args.length > 0 && (
                  <button onClick={() => retryExecution(e)} disabled={retrying === e.id}
                    className="flex items-center gap-1 rounded border border-line px-2 py-0.5 hover:bg-panel disabled:opacity-40">
                    {retrying === e.id ? <Spinner size={11} /> : <><RefreshCw size={11} /> retry</>}
                  </button>
                )}
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
            <div className="kai-metadata mt-2">
              A domain here also authorizes its subdomains, and URLs are stored as their host.
              Auto-authorization is on, so an active scan of a new target adds it here automatically
              (every addition is audited). Only point KAI at assets you own or are permitted to test.
            </div>
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
                <span className="kai-metadata">· {f.status === f.confidence ? f.status : `${f.confidence} · ${f.status}`}{f.tool ? ` · ${f.tool}` : ""}</span>
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
