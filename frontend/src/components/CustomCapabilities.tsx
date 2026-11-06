import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2, Save, Power, Wrench, ChevronDown, ChevronRight } from "lucide-react";

import {
  toolsApi, TARGET_KINDS, TOOL_SOURCES,
  type CustomCapability, type CapabilityIn, type CapabilityOpIn,
} from "@/lib/tools";

const inputCls = "rounded border border-line bg-panel px-2 py-1 text-xs outline-none focus:border-current";
const btnCls = "flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel disabled:opacity-40";

const EMPTY_OP: CapabilityOpIn = {
  key: "", title: "", description: "", posture: "passive", argv_template: "",
  target_kind: "", requires_authorization: false, timeout: null,
};
const EMPTY: CapabilityIn = {
  name: "", title: "", purpose: "", category: "custom", binary: "", source: "apt",
  package: "", categories: [], operations: [{ ...EMPTY_OP }], enabled: true,
};

function toDraft(r: CustomCapability): CapabilityIn & { id: string } {
  const e = r.entry || {};
  return {
    id: r.id, name: r.name, title: r.title, purpose: e.purpose || "", category: r.category,
    binary: e.binary || "", source: e.source || "apt", package: e.package || "",
    categories: e.categories || [], enabled: r.enabled,
    operations: (e.ops || []).map((o: any) => ({
      key: o.key, title: o.title || "", description: o.desc || "", posture: o.posture || "passive",
      argv_template: (o.template || []).filter((t: string) => t !== "{target}").join(" "),
      target_kind: o.target?.kind || "", requires_authorization: !!o.auth, timeout: o.timeout ?? null,
    })),
  };
}

export function CustomCapabilities() {
  const [caps, setCaps] = useState<CustomCapability[]>([]);
  const [draft, setDraft] = useState<(CapabilityIn & { id?: string }) | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setCaps(await toolsApi.customCapabilities()); } catch (e: any) { setMsg(e?.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save() {
    if (!draft) return;
    const body: CapabilityIn = { ...draft, categories: draft.categories || [] };
    try {
      if (draft.id) await toolsApi.updateCapability(draft.id, body);
      else await toolsApi.addCapability(body);
      setDraft(null); setMsg("Capability saved — it's now in the inventory, palette, and Kai's catalogue.");
      load();
    } catch (e: any) { setMsg(e?.message || "save failed"); }
  }
  async function toggle(r: CustomCapability) {
    try { await toolsApi.updateCapability(r.id, { ...toDraft(r), enabled: !r.enabled }); load(); }
    catch (e: any) { setMsg(e?.message); }
  }
  async function del(r: CustomCapability) {
    if (!confirm(`Delete capability '${r.name}'?`)) return;
    try { await toolsApi.deleteCapability(r.id); load(); } catch (e: any) { setMsg(e?.message); }
  }

  const setOp = (i: number, patch: Partial<CapabilityOpIn>) =>
    setDraft((d) => d && ({ ...d, operations: d.operations.map((o, j) => j === i ? { ...o, ...patch } : o) }));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted">
          Define your own tools (e.g. amass, wpscan, theHarvester, spiderfoot). They appear in the
          inventory, the chat capability palette, and Kai's runnable catalogue. Non-apt tools are
          installed by Kai via the terminal on first use.
        </div>
        {!draft && <button className={btnCls} onClick={() => setDraft({ ...EMPTY, operations: [{ ...EMPTY_OP }] })}><Plus size={12} /> add capability</button>}
      </div>
      {msg && <div className="rounded border border-line bg-panel-2 px-3 py-2 text-xs text-muted">{msg}</div>}

      {draft && (
        <div className="hud-panel hud-frame space-y-2 p-3">
          <div className="flex items-center justify-between">
            <div className="hud-mono text-xs uppercase" style={{ color: "var(--kai-hud)" }}>◢ {draft.id ? `Edit ${draft.name}` : "New capability"}</div>
            <div className="flex gap-1">
              <button className={btnCls} onClick={() => setDraft(null)}>cancel</button>
              <button className={btnCls} onClick={save}><Save size={12} /> save</button>
            </div>
          </div>
          <div className="grid gap-2 md:grid-cols-3 text-xs">
            <label className="block"><span className="kai-metadata uppercase">Name (tool)</span>
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="amass" className={`${inputCls} w-full font-mono`} /></label>
            <label className="block"><span className="kai-metadata uppercase">Binary (if different)</span>
              <input value={draft.binary} onChange={(e) => setDraft({ ...draft, binary: e.target.value })} placeholder="amass" className={`${inputCls} w-full font-mono`} /></label>
            <label className="block"><span className="kai-metadata uppercase">Install source</span>
              <select value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })} className={`${inputCls} w-full`}>
                {TOOL_SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}</select></label>
            <label className="block md:col-span-2"><span className="kai-metadata uppercase">Purpose (for Kai)</span>
              <input value={draft.purpose} onChange={(e) => setDraft({ ...draft, purpose: e.target.value })} placeholder="OWASP Amass — subdomain enumeration" className={`${inputCls} w-full`} /></label>
            <label className="block"><span className="kai-metadata uppercase">Install package/module/repo</span>
              <input value={draft.package} onChange={(e) => setDraft({ ...draft, package: e.target.value })} placeholder="github.com/owasp-amass/amass/v4/...@master" className={`${inputCls} w-full font-mono`} /></label>
            <label className="block md:col-span-3"><span className="kai-metadata uppercase">Categories (comma-sep)</span>
              <input defaultValue={(draft.categories || []).join(", ")} onChange={(e) => setDraft({ ...draft, categories: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} placeholder="recon, osint" className={`${inputCls} w-full`} /></label>
          </div>

          <div className="kai-metadata uppercase">Operations</div>
          {draft.operations.map((op, i) => (
            <div key={i} className="rounded border border-line bg-panel-2 p-2">
              <div className="grid gap-2 md:grid-cols-4 text-xs">
                <label className="block"><span className="kai-metadata uppercase">Op key</span>
                  <input value={op.key} onChange={(e) => setOp(i, { key: e.target.value })} placeholder="amass.enum" className={`${inputCls} w-full font-mono`} /></label>
                <label className="block"><span className="kai-metadata uppercase">Title</span>
                  <input value={op.title} onChange={(e) => setOp(i, { title: e.target.value })} placeholder="Subdomain enum" className={`${inputCls} w-full`} /></label>
                <label className="block"><span className="kai-metadata uppercase">Posture</span>
                  <select value={op.posture} onChange={(e) => setOp(i, { posture: e.target.value })} className={`${inputCls} w-full`}>
                    <option>passive</option><option>active</option><option>disruptive</option></select></label>
                <label className="block"><span className="kai-metadata uppercase">Target kind</span>
                  <select value={op.target_kind ?? ""} onChange={(e) => setOp(i, { target_kind: e.target.value })} className={`${inputCls} w-full`}>
                    {TARGET_KINDS.map((k) => <option key={k} value={k}>{k || "(none)"}</option>)}</select></label>
                <label className="block md:col-span-3"><span className="kai-metadata uppercase">Argv after binary — use {"{target}"}</span>
                  <input value={op.argv_template} onChange={(e) => setOp(i, { argv_template: e.target.value })} placeholder="enum -d {target}" className={`${inputCls} w-full font-mono`} /></label>
                <label className="block"><span className="kai-metadata uppercase">Timeout (s)</span>
                  <input type="number" value={op.timeout ?? ""} onChange={(e) => setOp(i, { timeout: e.target.value ? Number(e.target.value) : null })} className={`${inputCls} w-full`} /></label>
                <label className="block md:col-span-4"><span className="kai-metadata uppercase">Description</span>
                  <input value={op.description} onChange={(e) => setOp(i, { description: e.target.value })} className={`${inputCls} w-full`} /></label>
                <label className="flex items-center gap-1.5 text-muted">
                  <input type="checkbox" checked={!!op.requires_authorization} onChange={(e) => setOp(i, { requires_authorization: e.target.checked })} />
                  requires authorized target (active scans)
                </label>
              </div>
              {draft.operations.length > 1 && (
                <button className={`${btnCls} mt-2`} onClick={() => setDraft({ ...draft, operations: draft.operations.filter((_, j) => j !== i) })}>
                  <Trash2 size={11} /> remove op
                </button>
              )}
            </div>
          ))}
          <button className={btnCls} onClick={() => setDraft({ ...draft, operations: [...draft.operations, { ...EMPTY_OP }] })}><Plus size={11} /> add operation</button>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={draft.enabled ?? true} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /> enabled
          </label>
        </div>
      )}

      <div className="grid gap-2">
        {caps.length === 0 && !draft && <div className="text-xs text-muted">No custom capabilities yet.</div>}
        {caps.map((r) => (
          <div key={r.id} className="hud-panel hud-frame p-3 text-xs">
            <div className="flex items-center justify-between">
              <button className="flex items-center gap-1.5" onClick={() => setExpanded(expanded === r.id ? null : r.id)}>
                {expanded === r.id ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <Wrench size={12} style={{ color: "var(--kai-hud)" }} />
                <span className="font-mono" style={{ color: "var(--kai-hud)" }}>{r.name}</span>
                <span className="rounded bg-panel-2 px-1.5 py-0.5 text-[10px] uppercase text-muted">{r.source}</span>
                <span className="text-muted">· {r.operations.length} op{r.operations.length === 1 ? "" : "s"}</span>
              </button>
              <div className="flex gap-1">
                <button className={btnCls} onClick={() => toggle(r)}><Power size={11} style={{ color: r.enabled ? "var(--kai-verified)" : "var(--kai-muted)" }} /> {r.enabled ? "on" : "off"}</button>
                <button className={btnCls} onClick={() => setDraft(toDraft(r))}><Save size={11} /> edit</button>
                <button className={btnCls} onClick={() => del(r)}><Trash2 size={11} /></button>
              </div>
            </div>
            {expanded === r.id && (
              <div className="mt-2 space-y-1 border-t border-line pt-2">
                <div className="text-muted">{r.entry?.purpose}</div>
                {r.operations.map((o: any) => (
                  <div key={o.key} className="font-mono text-[11px] text-muted">
                    {o.key} <span style={{ color: "var(--kai-hud)" }}>({o.posture})</span>{o.auth ? " · needs auth" : ""} — {(o.template || []).join(" ")}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
