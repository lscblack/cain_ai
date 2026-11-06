import { useCallback, useEffect, useRef, useState } from "react";
import {
  Landmark, Play, Pause, Square, RefreshCw, Upload, Search, Database, Phone as PhoneIcon,
  IdCard, MapPin, Users, Plug, Plus, Trash2, FlaskConical, Save,
} from "lucide-react";

import {
  enrichApi, type EndpointCfg, type EndpointIn, type ScrapeJob, type PersonRow,
  type ParcelRow, type EnrichStats,
} from "@/lib/enrich";
import { AuthImg } from "@/components/AuthImg";
import { JsonView } from "@/components/JsonView";

const TABS = ["Overview", "Scrape", "People", "Parcels", "Endpoints"] as const;
type Tab = (typeof TABS)[number];

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

const inputCls = "rounded border border-line bg-panel px-2 py-1 text-xs outline-none focus:border-current";
const btnCls = "flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel disabled:opacity-40";

const STATUS_COLOR: Record<string, string> = {
  running: "var(--kai-hud)", done: "var(--kai-verified)", error: "var(--kai-accent)",
  cancelled: "#f59e0b", paused: "#f59e0b", queued: "var(--kai-hud)",
};

function JobCard({ job, onControl }: { job: ScrapeJob; onControl: (a: "pause" | "resume" | "cancel") => void }) {
  const pct = job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0;
  const stats = job.stats || {};
  const active = job.status === "running" || job.status === "paused";
  return (
    <div className="rounded border border-line bg-panel-2 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div className="hud-mono">{job.kind} · <span style={{ color: STATUS_COLOR[job.status] || "var(--kai-muted)" }}>● {job.status}</span></div>
        <div className="flex gap-1">
          {active && job.status === "running" && <button className={btnCls} onClick={() => onControl("pause")}><Pause size={11} /> pause</button>}
          {active && job.status === "paused" && <button className={btnCls} onClick={() => onControl("resume")}><Play size={11} /> resume</button>}
          {active && <button className={btnCls} onClick={() => onControl("cancel")}><Square size={11} /> stop</button>}
          {!active && job.status === "error" && <button className={btnCls} onClick={() => onControl("resume")}><RefreshCw size={11} /> retry</button>}
        </div>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-panel">
        <div className="h-full" style={{ width: `${pct}%`, background: "var(--kai-hud)" }} />
      </div>
      <div className="mt-1 text-muted">{job.processed}/{job.total} ({pct}%) · {job.last_message}</div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
        {Object.entries(stats).map(([k, v]) => (
          <span key={k}><b style={{ color: "var(--kai-text)" }}>{v}</b> {k.replace(/_/g, " ")}</span>
        ))}
      </div>
    </div>
  );
}

export function LandRegistry() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [stats, setStats] = useState<EnrichStats | null>(null);
  const [jobs, setJobs] = useState<ScrapeJob[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  // scrape forms
  const [phoneText, setPhoneText] = useState("");
  const [nidText, setNidText] = useState("");
  const [rate, setRate] = useState(10);
  const [expand, setExpand] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const [s, j] = await Promise.all([enrichApi.stats(), enrichApi.jobs()]);
      setStats(s); setJobs(j);
    } catch { /* */ }
  }, []);

  useEffect(() => { refreshStatus(); }, [refreshStatus]);

  // Poll while any job is active or we're on Overview/Scrape.
  useEffect(() => {
    const anyActive = jobs.some((j) => j.running || j.status === "running" || j.status === "queued");
    if (!anyActive && tab !== "Overview" && tab !== "Scrape") return;
    const id = setInterval(refreshStatus, 3000);
    return () => clearInterval(id);
  }, [jobs, tab, refreshStatus]);

  async function startPhone() {
    const phones = phoneText.split(/[\s,;]+/).map((p) => p.trim()).filter(Boolean);
    if (!phones.length) { setMsg("Enter at least one phone number."); return; }
    try { await enrichApi.startPhone(phones, rate); setMsg(`Started phone job for ${phones.length} number(s).`); setPhoneText(""); refreshStatus(); }
    catch (e: any) { setMsg(e?.message || "failed"); }
  }
  async function startNid() {
    const nids = nidText.split(/[\s,;]+/).map((p) => p.trim()).filter(Boolean);
    if (!nids.length) { setMsg("Enter at least one NID."); return; }
    try { await enrichApi.startNid(nids, rate); setMsg(`Started NID job for ${nids.length} ID(s).`); setNidText(""); refreshStatus(); }
    catch (e: any) { setMsg(e?.message || "failed"); }
  }
  async function startCsv(f: File) {
    try { const j = await enrichApi.startCsv(f, rate, expand); setMsg(`CSV uploaded: ${j.parsed_rows ?? "?"} rows queued.`); refreshStatus(); }
    catch (e: any) { setMsg(e?.message || "CSV upload failed"); }
    if (fileRef.current) fileRef.current.value = "";
  }
  async function control(id: string, action: "pause" | "resume" | "cancel") {
    try { await enrichApi.controlJob(id, action); refreshStatus(); } catch (e: any) { setMsg(e?.message || "failed"); }
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center gap-2">
        <Landmark size={18} style={{ color: "var(--kai-hud)" }} />
        <h1 className="text-lg font-semibold">Land Registry &amp; Identity Enrichment</h1>
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-line pb-2">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`whitespace-nowrap rounded px-3 py-1 text-xs ${tab === t ? "bg-panel text-text" : "text-muted hover:bg-panel-2"}`}>
            {t}
          </button>
        ))}
      </div>

      {msg && <div className="rounded border border-line bg-panel-2 px-3 py-2 text-xs text-muted">{msg}</div>}

      {tab === "Overview" && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {[
            { icon: Users, label: "People", v: stats?.persons },
            { icon: MapPin, label: "Parcels", v: stats?.parcels },
            { icon: PhoneIcon, label: "Phones", v: stats?.phones },
            { icon: Database, label: "Ownership", v: stats?.ownership_records },
            { icon: Play, label: "Jobs", v: stats?.jobs },
          ].map(({ icon: Icon, label, v }) => (
            <div key={label} className="hud-panel hud-frame flex flex-col items-start gap-1 p-4">
              <Icon size={16} style={{ color: "var(--kai-hud)" }} />
              <div className="text-2xl font-semibold">{v ?? "—"}</div>
              <div className="kai-metadata uppercase">{label}</div>
            </div>
          ))}
          <div className="col-span-2 md:col-span-5">
            <Panel title="Recent jobs" right={<button className={btnCls} onClick={refreshStatus}><RefreshCw size={12} /> refresh</button>}>
              {jobs.length === 0 ? <div className="text-xs text-muted">No jobs yet.</div> : (
                <div className="space-y-2">{jobs.slice(0, 5).map((j) => <JobCard key={j.id} job={j} onControl={(a) => control(j.id, a)} />)}</div>
              )}
            </Panel>
          </div>
        </div>
      )}

      {tab === "Scrape" && (
        <div className="grid gap-3 md:grid-cols-2">
          <Panel title="Seed from phone numbers">
            <p className="mb-2 text-[11px] text-muted">phone → NID → citizen record (+ face) → phones → parcels. One per line or comma-separated.</p>
            <textarea value={phoneText} onChange={(e) => setPhoneText(e.target.value)} rows={4}
              placeholder="0790110231&#10;0739300511" className={`${inputCls} w-full font-mono`} />
            <button className={`${btnCls} mt-2`} onClick={startPhone}><Play size={12} /> start phone job</button>
          </Panel>

          <Panel title="Seed from national IDs">
            <p className="mb-2 text-[11px] text-muted">Directly enrich a list of NIDs.</p>
            <textarea value={nidText} onChange={(e) => setNidText(e.target.value)} rows={4}
              placeholder="1200480002578150" className={`${inputCls} w-full font-mono`} />
            <button className={`${btnCls} mt-2`} onClick={startNid}><Play size={12} /> start NID job</button>
          </Panel>

          <Panel title="Seed from UPI CSV">
            <p className="mb-2 text-[11px] text-muted">
              Columns: provincename, districtname, sectorname, cellname, village, upi, size,
              land_use_name_kinyarwanda, transaction_type_name, sale_price, start_date, Year.
              Each UPI is reverse-looked-up to its owner(s) via the <b>upi_owners</b> endpoint.
            </p>
            <label className="mb-2 flex items-center gap-2 text-[11px] text-muted">
              <input type="checkbox" checked={expand} onChange={(e) => setExpand(e.target.checked)} />
              also fetch each owner's other parcels (slower)
            </label>
            <input ref={fileRef} type="file" accept=".csv,text/csv"
              onChange={(e) => e.target.files?.[0] && startCsv(e.target.files[0])}
              className="hidden" />
            <button className={btnCls} onClick={() => fileRef.current?.click()}><Upload size={12} /> upload CSV</button>
          </Panel>

          <Panel title="Rate limit">
            <label className="flex items-center gap-2 text-xs">
              <input type="number" min={1} max={120} value={rate}
                onChange={(e) => setRate(Math.max(1, Math.min(120, Number(e.target.value) || 10)))}
                className={`${inputCls} w-20`} /> requests / minute (per job)
            </label>
            <p className="mt-2 text-[11px] text-muted">Applies to every external endpoint call in a job. Default 10/min.</p>
          </Panel>

          <div className="md:col-span-2">
            <Panel title="Active & recent jobs" right={<button className={btnCls} onClick={refreshStatus}><RefreshCw size={12} /> refresh</button>}>
              {jobs.length === 0 ? <div className="text-xs text-muted">No jobs yet.</div> : (
                <div className="space-y-2">{jobs.map((j) => <JobCard key={j.id} job={j} onControl={(a) => control(j.id, a)} />)}</div>
              )}
            </Panel>
          </div>
        </div>
      )}

      {tab === "People" && <PeopleTab />}
      {tab === "Parcels" && <ParcelsTab />}
      {tab === "Endpoints" && <EndpointsTab onMsg={setMsg} />}
    </div>
  );
}

// ───────────────────────── People ───────────────────────────────────────── #
function PeopleTab() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<PersonRow[]>([]);
  const [sel, setSel] = useState<PersonRow | null>(null);

  const load = useCallback(async () => { try { setRows(await enrichApi.persons(q)); } catch { /* */ } }, [q]);
  useEffect(() => { load(); }, [load]);

  async function open(nid: string) { try { setSel(await enrichApi.person(nid)); } catch { /* */ } }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Panel title="People" right={
        <div className="flex gap-1">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="name / NID / district" className={`${inputCls} w-40`} />
          <button className={btnCls} onClick={load}><Search size={12} /></button>
        </div>
      }>
        <div className="max-h-[60vh] space-y-1 overflow-auto">
          {rows.length === 0 && <div className="text-xs text-muted">No people yet — run a scrape.</div>}
          {rows.map((p) => (
            <button key={p.id} onClick={() => open(p.nid)}
              className="flex w-full items-center gap-2 rounded border border-line bg-panel-2 p-2 text-left text-xs hover:bg-panel">
              {p.crop_url ? <AuthImg path={p.crop_url} className="h-9 w-9 rounded object-cover" /> : <IdCard size={18} className="text-muted" />}
              <div>
                <div className="font-medium">{p.name}</div>
                <div className="text-[11px] text-muted">{p.nid} · {p.district || "—"}</div>
              </div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel title="Record">
        {!sel ? <div className="text-xs text-muted">Select a person.</div> : (
          <div className="space-y-2 text-xs">
            <div className="flex items-center gap-3">
              {sel.crop_url ? <AuthImg path={sel.crop_url} className="h-20 w-20 rounded object-cover" /> : <IdCard size={40} className="text-muted" />}
              <div>
                <div className="text-base font-semibold">{sel.name}</div>
                <div className="text-muted">NID {sel.nid}</div>
                <div className="text-muted">{sel.sex} · DOB {sel.date_of_birth || "—"}</div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              {[["Father", sel.father_names], ["Mother", sel.mother_names], ["Nationality", sel.nationality],
                ["Civil status", sel.civil_status], ["Place of birth", sel.place_of_birth], ["Document", sel.document_number],
                ["Province", sel.province], ["District", sel.district], ["Sector", sel.sector],
                ["Cell", sel.cell], ["Village", sel.village], ["Issued / expires", `${sel.date_of_issue || "—"} → ${sel.date_of_expiry || "—"}`]]
                .map(([k, v]) => <div key={k as string}><span className="text-muted">{k}: </span>{(v as string) || "—"}</div>)}
            </div>
            <div>
              <div className="hud-mono text-[11px] uppercase" style={{ color: "var(--kai-hud)" }}>Phones ({sel.phones?.length || 0})</div>
              {(sel.phones || []).map((ph, i) => <div key={i} className="text-muted">{ph.msisdn} {ph.mno ? `· ${ph.mno}` : ""} {ph.service_period ? `· ${ph.service_period}` : ""}</div>)}
            </div>
            <div>
              <div className="hud-mono text-[11px] uppercase" style={{ color: "var(--kai-hud)" }}>Parcels owned ({sel.upi_count || 0})</div>
              {(sel.parcels || []).map((p, i) => <div key={i} className="text-muted">{p.upi} {p.is_current ? "· current" : `· past (ended ${p.end_date || "?"})`}</div>)}
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

// ───────────────────────── Parcels ──────────────────────────────────────── #
function ParcelsTab() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<ParcelRow[]>([]);
  const [sel, setSel] = useState<ParcelRow | null>(null);

  const load = useCallback(async () => { try { setRows(await enrichApi.parcels(q)); } catch { /* */ } }, [q]);
  useEffect(() => { load(); }, [load]);
  async function open(upi: string) { try { setSel(await enrichApi.parcel(upi)); } catch { /* */ } }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Panel title="Parcels" right={
        <div className="flex gap-1">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="UPI / district / owner NID" className={`${inputCls} w-40`} />
          <button className={btnCls} onClick={load}><Search size={12} /></button>
        </div>
      }>
        <div className="max-h-[60vh] space-y-1 overflow-auto">
          {rows.length === 0 && <div className="text-xs text-muted">No parcels yet.</div>}
          {rows.map((p) => (
            <button key={p.id} onClick={() => open(p.upi)}
              className="flex w-full items-center justify-between rounded border border-line bg-panel-2 p-2 text-left text-xs hover:bg-panel">
              <div>
                <div className="font-mono">{p.upi}</div>
                <div className="text-[11px] text-muted">{p.district || "—"} · {p.land_use || "—"} · {p.size ?? "?"}m²</div>
              </div>
              <div className="text-[11px] text-muted">{p.current_owner_nid || "no owner"}</div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel title="Ownership history">
        {!sel ? <div className="text-xs text-muted">Select a parcel.</div> : (
          <div className="space-y-2 text-xs">
            <div className="font-mono text-sm">{sel.upi}</div>
            <div className="text-muted">{[sel.province, sel.district, sel.sector, sel.cell, sel.village].filter(Boolean).join(" / ")}</div>
            <div className="text-muted">{sel.land_use || "—"} · {sel.size ?? "?"}m² · current owner: {sel.current_owner_nid || "unknown"}</div>
            <div className="mt-2 space-y-1">
              {(sel.ownership_history || []).map((o, i) => (
                <div key={i} className="rounded border border-line bg-panel-2 p-2">
                  <div className="flex items-center justify-between">
                    <span className="font-mono">{o.owner_nid || "(transaction)"}</span>
                    <span style={{ color: o.is_current ? "var(--kai-verified)" : "var(--kai-muted)" }}>{o.is_current ? "● current" : "past"}</span>
                  </div>
                  <div className="text-[11px] text-muted">
                    {o.transaction_type || "ownership"}{o.sale_price ? ` · ${o.sale_price.toLocaleString()} RWF` : ""}
                    {o.start_date ? ` · from ${o.start_date}` : ""}{o.end_date ? ` → ${o.end_date}` : ""} · src {o.source}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

// ───────────────────────── Endpoints ────────────────────────────────────── #
const EMPTY_EP: EndpointIn = {
  slug: "", title: "", category: "general", description: "", kind: "custom", method: "GET",
  url_template: "", query_template: {}, headers: {}, body_template: {}, auth_type: "none",
  auth_config: {}, result_path: "", image_keys: [], enabled: true, rate_limit_per_min: 10,
  sample_response: "",
};

function EndpointsTab({ onMsg }: { onMsg: (m: string) => void }) {
  const [eps, setEps] = useState<EndpointCfg[]>([]);
  const [kinds, setKinds] = useState<string[]>([]);
  const [editing, setEditing] = useState<EndpointCfg | "new" | null>(null);
  const [testParams, setTestParams] = useState<Record<string, string>>({ nid: "", phone: "", upi: "" });
  const [testRes, setTestRes] = useState<any>(null);

  const load = useCallback(async () => {
    try { const r = await enrichApi.endpoints(); setEps(r.endpoints); setKinds(r.kinds); } catch { /* */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function toggle(e: EndpointCfg) {
    const { id, created_at, ...rest } = e as any;
    try { await enrichApi.updateEndpoint(e.id, { ...rest, enabled: !e.enabled }); load(); } catch (err: any) { onMsg(err?.message); }
  }
  async function del(e: EndpointCfg) {
    if (!confirm(`Delete endpoint '${e.slug}'?`)) return;
    try { await enrichApi.deleteEndpoint(e.id); load(); } catch (err: any) { onMsg(err?.message); }
  }
  async function runTest(e: EndpointCfg) {
    const params = Object.fromEntries(Object.entries(testParams).filter(([, v]) => v));
    try { setTestRes(await enrichApi.testEndpoint(e.id, params)); } catch (err: any) { setTestRes({ ok: false, error: err?.message }); }
  }

  if (editing) return <EndpointEditor initial={editing === "new" ? EMPTY_EP : editing} kinds={kinds}
    onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} onMsg={onMsg} />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted">Endpoints KAI can query (also available to chat via <span className="font-mono">data.lookup</span>). Secrets are referenced from <span className="font-mono">.env</span> as <span className="font-mono">{"{env:VAR}"}</span>.</div>
        <button className={btnCls} onClick={() => setEditing("new")}><Plus size={12} /> add endpoint</button>
      </div>
      <div className="grid gap-2">
        {eps.map((e) => (
          <div key={e.id} className="hud-panel hud-frame p-3 text-xs">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-mono" style={{ color: "var(--kai-hud)" }}>{e.slug}</span>
                <span className="ml-2 rounded bg-panel-2 px-1.5 py-0.5 text-[10px] uppercase text-muted">{e.category}</span>
                <span className="ml-1 rounded bg-panel-2 px-1.5 py-0.5 text-[10px] uppercase text-muted">{e.kind}</span>
                {e.auth_type !== "none" && <span className="ml-1 rounded bg-panel-2 px-1.5 py-0.5 text-[10px] uppercase text-muted">{e.auth_type}</span>}
              </div>
              <div className="flex gap-1">
                <button className={btnCls} onClick={() => toggle(e)} title="enable/disable">
                  <Plug size={11} style={{ color: e.enabled ? "var(--kai-verified)" : "var(--kai-muted)" }} /> {e.enabled ? "on" : "off"}
                </button>
                <button className={btnCls} onClick={() => setEditing(e)}><Save size={11} /> edit</button>
                <button className={btnCls} onClick={() => del(e)}><Trash2 size={11} /></button>
              </div>
            </div>
            <div className="mt-1 font-medium">{e.title}</div>
            <div className="text-muted">{e.description}</div>
            <div className="mt-1 font-mono text-[11px] text-muted">{e.method} {e.url_template}</div>
            {e.image_keys.length > 0 && <div className="text-[11px] text-muted">images: {e.image_keys.join(", ")}</div>}
            <div className="mt-2 flex flex-wrap items-end gap-1 border-t border-line pt-2">
              {["nid", "phone", "upi"].map((k) => (
                <input key={k} placeholder={k} value={testParams[k]} onChange={(ev) => setTestParams((s) => ({ ...s, [k]: ev.target.value }))} className={`${inputCls} w-28`} />
              ))}
              <button className={btnCls} onClick={() => runTest(e)}><FlaskConical size={11} /> test</button>
            </div>
          </div>
        ))}
      </div>
      {testRes && (
        <Panel title="Test result">
          <div className="hud-mono text-xs" style={{ color: testRes.ok ? "var(--kai-verified)" : "var(--kai-accent)" }}>
            ● {testRes.ok ? `ok (HTTP ${testRes.status})` : `error: ${testRes.error}`} {testRes.url ? `· ${testRes.url}` : ""}
          </div>
          {testRes.images_found?.length > 0 && <div className="text-[11px] text-muted">images found: {testRes.images_found.join(", ")}</div>}
          {testRes.data != null && <JsonView value={testRes.data} />}
        </Panel>
      )}
    </div>
  );
}

function EndpointEditor({ initial, kinds, onCancel, onSaved, onMsg }: {
  initial: EndpointIn; kinds: string[]; onCancel: () => void; onSaved: () => void; onMsg: (m: string) => void;
}) {
  const [f, setF] = useState<EndpointIn>({ ...initial });
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const set = (k: keyof EndpointIn, v: any) => setF((s) => ({ ...s, [k]: v }));

  function jsonField(label: string, key: keyof EndpointIn) {
    return (
      <label className="block">
        <span className="kai-metadata uppercase">{label}</span>
        <textarea rows={3} defaultValue={JSON.stringify((f as any)[key] ?? {}, null, 2)}
          onChange={(e) => { try { set(key, JSON.parse(e.target.value || "{}")); setJsonErr(null); } catch { setJsonErr(`${label} is not valid JSON`); } }}
          className={`${inputCls} w-full font-mono`} />
      </label>
    );
  }

  async function save() {
    if (jsonErr) { onMsg(jsonErr); return; }
    const body: EndpointIn = { ...f, image_keys: Array.isArray(f.image_keys) ? f.image_keys : String(f.image_keys).split(",").map((s) => s.trim()).filter(Boolean) };
    try {
      if ((initial as any).slug && (initial as EndpointCfg & { id?: string })) {
        // editing an existing one has an id on the source object
      }
      const existingId = (initial as any as EndpointCfg).id;
      if (existingId) await enrichApi.updateEndpoint(existingId, body);
      else await enrichApi.createEndpoint(body);
      onSaved();
    } catch (e: any) { onMsg(e?.message || "save failed"); }
  }

  return (
    <Panel title={(initial as any as EndpointCfg).id ? `Edit ${f.slug}` : "New endpoint"} right={
      <div className="flex gap-1">
        <button className={btnCls} onClick={onCancel}>cancel</button>
        <button className={btnCls} onClick={save}><Save size={12} /> save</button>
      </div>
    }>
      <div className="grid gap-2 text-xs md:grid-cols-2">
        <label className="block"><span className="kai-metadata uppercase">Slug</span>
          <input value={f.slug} onChange={(e) => set("slug", e.target.value)} className={`${inputCls} w-full`} /></label>
        <label className="block"><span className="kai-metadata uppercase">Title</span>
          <input value={f.title} onChange={(e) => set("title", e.target.value)} className={`${inputCls} w-full`} /></label>
        <label className="block"><span className="kai-metadata uppercase">Category</span>
          <input value={f.category} onChange={(e) => set("category", e.target.value)} className={`${inputCls} w-full`} /></label>
        <label className="block"><span className="kai-metadata uppercase">Kind (scraper role)</span>
          <select value={f.kind} onChange={(e) => set("kind", e.target.value)} className={`${inputCls} w-full`}>
            {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select></label>
        <label className="block md:col-span-2"><span className="kai-metadata uppercase">Description (for KAI)</span>
          <textarea rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} className={`${inputCls} w-full`} /></label>
        <label className="block"><span className="kai-metadata uppercase">Method</span>
          <select value={f.method} onChange={(e) => set("method", e.target.value)} className={`${inputCls} w-full`}>
            <option>GET</option><option>POST</option></select></label>
        <label className="block"><span className="kai-metadata uppercase">URL template</span>
          <input value={f.url_template} onChange={(e) => set("url_template", e.target.value)} placeholder="http://127.0.0.1:8585/person/{nid}" className={`${inputCls} w-full font-mono`} /></label>
        <label className="block"><span className="kai-metadata uppercase">Result path (dotted)</span>
          <input value={f.result_path} onChange={(e) => set("result_path", e.target.value)} placeholder="GetCitizenResult" className={`${inputCls} w-full font-mono`} /></label>
        <label className="block"><span className="kai-metadata uppercase">Image keys (comma-sep)</span>
          <input defaultValue={(f.image_keys || []).join(", ")} onChange={(e) => set("image_keys", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} placeholder="Photo, Signature" className={`${inputCls} w-full font-mono`} /></label>
        <label className="block"><span className="kai-metadata uppercase">Auth type</span>
          <select value={f.auth_type} onChange={(e) => set("auth_type", e.target.value)} className={`${inputCls} w-full`}>
            <option>none</option><option>bearer</option><option>header_key</option><option>basic</option></select></label>
        <label className="block"><span className="kai-metadata uppercase">Rate limit / min</span>
          <input type="number" value={f.rate_limit_per_min} onChange={(e) => set("rate_limit_per_min", Number(e.target.value) || 10)} className={`${inputCls} w-full`} /></label>
        {jsonField("Query template (JSON)", "query_template")}
        {jsonField("Headers (JSON)", "headers")}
        {jsonField("Body template (JSON)", "body_template")}
        {jsonField("Auth config (JSON, use {env:VAR})", "auth_config")}
      </div>
      {jsonErr && <div className="mt-2 text-xs" style={{ color: "var(--kai-accent)" }}>{jsonErr}</div>}
    </Panel>
  );
}
