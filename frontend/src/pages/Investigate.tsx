import { useEffect, useRef, useState } from "react";
import { Crosshair, Play, Users, Radar, Trash2, ChevronRight, RotateCw } from "lucide-react";

import { api } from "@/lib/api";
import { AuthImg } from "@/components/AuthImg";

interface Face { face_id: string; crop_url: string; source_url: string | null; description?: string | null }
interface PageHit { url: string; title: string | null; emails: string[]; phones: string[]; usernames: string[] }
interface Dossier {
  term: string;
  detected_type: string;
  faces: Face[];
  pages: PageHit[];
  phones: string[];
  emails: string[];
  usernames: string[];
  counts: { faces: number; pages: number; phones: number; emails: number; usernames: number };
}
interface Investigation { id: string; status: string; names: string[]; approved: number; progress: number; started_at?: number }
interface SearchRow { term: string; kind: string; count: number; local_hits?: number; pending?: boolean; dossier: Dossier }

type Tab = "names" | "public";

function Chips({ items, color }: { items: string[]; color?: string }) {
  if (!items?.length) return null;
  return (
    <div className="flex flex-wrap gap-1 font-mono text-[10px]">
      {items.map((v) => (
        <span key={v} className="truncate border border-line px-1.5 py-0.5" style={{ color, maxWidth: "100%" }}>{v}</span>
      ))}
    </div>
  );
}

function DossierView({ d }: { d: Dossier }) {
  const empty = d.counts.faces + d.counts.pages + d.counts.phones + d.counts.emails + d.counts.usernames === 0;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-5 gap-2 text-center">
        {(["faces", "phones", "emails", "usernames", "pages"] as const).map((k) => (
          <div key={k} className="border border-line bg-base px-1 py-2">
            <div className="text-lg font-semibold text-accent">{d.counts[k]}</div>
            <div className="kai-metadata">{k}</div>
          </div>
        ))}
      </div>

      {empty && <div className="border border-line bg-panel-2 px-3 py-6 text-center text-sm text-muted">Nothing indexed yet — discovery is still crawling. Re-open shortly.</div>}

      {d.faces.length > 0 && (
        <div>
          <div className="kai-metadata mb-2 uppercase">Images ({d.faces.length})</div>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8">
            {d.faces.map((f) => (
              <a key={f.face_id} href={f.source_url ?? undefined} target="_blank" rel="noreferrer" title={f.description ?? ""} className="group block">
                <AuthImg path={f.crop_url} className="aspect-square w-full border border-line object-cover transition group-hover:border-accent" />
              </a>
            ))}
          </div>
        </div>
      )}

      {(d.phones.length > 0 || d.emails.length > 0 || d.usernames.length > 0) && (
        <div className="space-y-2">
          <div className="kai-metadata uppercase">Linked identifiers</div>
          <Chips items={d.phones} color="var(--kai-verified)" />
          <Chips items={d.emails} color="var(--kai-warn)" />
          <Chips items={d.usernames} color="var(--kai-muted)" />
        </div>
      )}

      {d.pages.length > 0 && (
        <div>
          <div className="kai-metadata mb-2 uppercase">Pages ({d.pages.length})</div>
          <div className="max-h-56 space-y-1 overflow-auto">
            {d.pages.map((p) => {
              const onion = /\.onion(\/|$|:)/i.test(p.url);
              return (
                <a key={p.url} href={p.url} target="_blank" rel="noreferrer" title={p.url} className="flex items-center gap-1.5 truncate border border-line bg-base px-2 py-1.5 font-mono text-[11px] text-muted hover:border-accent hover:text-ink">
                  {onion && <span title="dark web (.onion)" className="shrink-0 text-accent">🧅</span>}
                  <span className="truncate">{p.title || p.url}</span>
                </a>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function Investigate() {
  const [tab, setTab] = useState<Tab>("names");
  return (
    <div className="w-11/12 max-w-[1700px] mx-auto space-y-5">
      <header className="flex items-center gap-3">
        <Crosshair className="text-accent" size={22} />
        <div>
          <h1 className="text-xl font-semibold tracking-wide">Investigations</h1>
          <p className="kai-metadata">Name dossiers · auto-discovery of what might belong to them</p>
        </div>
      </header>
      <div className="flex gap-1">
        {([["names", "Name investigations", Users], ["public", "Public searches", Radar]] as const).map(([k, label, Icon]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`flex items-center gap-2 border px-3 py-2 text-xs uppercase tracking-wider transition ${tab === k ? "border-accent text-accent" : "border-line text-muted hover:text-ink"}`}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>
      {tab === "names" ? <NamesTab /> : <PublicTab />}
    </div>
  );
}

function NamesTab() {
  const [text, setText] = useState("");
  const [autoCrawl, setAutoCrawl] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [runs, setRuns] = useState<Investigation[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [activeName, setActiveName] = useState<string | null>(null);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  async function load() {
    try { setRuns((await api.get<{ investigations: Investigation[] }>("/discovery/investigations")).investigations); } catch { /* */ }
  }
  useEffect(() => { load(); return () => { if (poll.current) clearInterval(poll.current); }; }, []);

  async function start() {
    const names = text.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean);
    if (names.length === 0) { setMsg("Enter at least one name."); return; }
    setMsg(null);
    try {
      const r = await api.post<{ id: string }>("/discovery/investigate", { names, auto_crawl: autoCrawl });
      setMsg(`Investigation started for ${names.length} name(s) — running in background.`);
      setText("");
      await load();
      open(r.id);
    } catch (e: any) {
      setMsg(e?.detail || "Failed to start investigation.");
    }
  }

  async function reinvestigate(names: string[], e: React.MouseEvent) {
    e.stopPropagation();
    if (names.length === 0) return;
    try {
      const r = await api.post<{ id: string }>("/discovery/investigate", { names, auto_crawl: autoCrawl });
      setMsg(`Re-investigating ${names.length} name(s)…`);
      await load();
      open(r.id);
    } catch (e: any) {
      setMsg(e?.detail || "Re-investigate failed.");
    }
  }

  async function open(id: string) {
    setOpenId(id);
    setActiveName(null);
    const fetchDetail = async () => {
      try {
        const d = await api.get<any>(`/discovery/investigations/${id}`);
        setDetail(d);
        setActiveName((cur) => cur ?? d.names?.[0] ?? null);
        if (d.status === "done" && poll.current) { clearInterval(poll.current); poll.current = null; load(); }
      } catch { /* */ }
    };
    if (poll.current) clearInterval(poll.current);
    poll.current = setInterval(fetchDetail, 4000);
    fetchDetail();
  }

  const activeDossier: Dossier | undefined = detail?.dossiers?.find((x: Dossier) => x.term === activeName);

  return (
    <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
      <div className="space-y-4">
        <section className="border border-line bg-panel-2 p-4">
          <div className="mb-2 kai-metadata uppercase">Upload names</div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            placeholder={"One name per line, e.g.\nPaul Kagame\nJane Doe\nJohn Smith"}
            className="w-full border border-line bg-base px-3 py-2 font-mono text-sm text-ink outline-none focus:border-accent"
          />
          <label className="mt-2 flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={autoCrawl} onChange={(e) => setAutoCrawl(e.target.checked)} />
            Auto-crawl discovered sources (find more)
          </label>
          <button onClick={start} className="mt-3 flex w-full items-center justify-center gap-2 border border-accent bg-accent/10 px-4 py-2.5 text-sm uppercase tracking-wider text-accent transition hover:bg-accent/20">
            <Play size={15} /> Start investigation
          </button>
          {msg && <p className="mt-2 text-xs text-muted">{msg}</p>}
        </section>

        <section className="border border-line bg-panel-2 p-4">
          <div className="mb-2 kai-metadata uppercase">Recent investigations</div>
          {runs.length === 0 ? <p className="text-sm text-muted">None yet.</p> : (
            <div className="space-y-1">
              {runs.map((r) => (
                <div key={r.id}
                  className={`flex items-center justify-between border px-2.5 py-2 text-xs transition ${openId === r.id ? "border-accent" : "border-line hover:border-muted"}`}>
                  <button onClick={() => open(r.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                    <span className="min-w-0 flex-1 truncate font-mono text-ink">{r.names.slice(0, 3).join(", ")}{r.names.length > 3 ? `  +${r.names.length - 3}` : ""}</span>
                    <span className={`shrink-0 uppercase ${r.status === "done" ? "text-verified" : "text-accent"}`}>{r.status}</span>
                  </button>
                  <button onClick={(e) => reinvestigate(r.names, e)} title="Re-investigate these names (fresh crawl)"
                    className="ml-2 shrink-0 text-muted transition hover:text-accent">
                    <RotateCw size={13} />
                  </button>
                  <ChevronRight size={13} className="ml-1 shrink-0 text-muted" />
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="border border-line bg-panel-2 p-4">
        {!detail ? (
          <div className="flex h-full min-h-48 items-center justify-center text-sm text-muted">Select or start an investigation to see dossiers.</div>
        ) : (
          <>
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="kai-metadata uppercase">Dossiers</span>
              <div className="flex items-center gap-3">
                <button
                  onClick={(e) => reinvestigate(detail.names ?? [], e)}
                  title="Run this investigation again with a fresh crawl"
                  className="flex items-center gap-1.5 border border-accent px-2.5 py-1 text-[10px] uppercase tracking-wider text-accent transition hover:bg-accent/10"
                >
                  <RotateCw size={12} /> Re-investigate
                </button>
                <span className={`text-xs uppercase ${detail.status === "done" ? "text-verified" : "text-accent"}`}>{detail.status}</span>
              </div>
            </div>
            <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px] uppercase tracking-wider text-muted">
              <span>sources approved: <span className="text-ink">{detail.approved ?? 0}</span></span>
              <span>new domains: <span className="text-ink">{detail.new_domains ?? 0}</span></span>
              <span className={detail.onion_enabled ? "" : "opacity-50"}>
                🧅 dark web: {detail.onion_enabled ? <span className="text-accent">{detail.onion_sources ?? 0} onion source(s)</span> : "tor off"}
              </span>
            </div>
            <div className="mb-3 flex flex-wrap gap-1">
              {(detail.names ?? []).map((n: string) => {
                const dd = detail.dossiers?.find((x: Dossier) => x.term === n);
                const total = dd ? dd.counts.faces + dd.counts.phones + dd.counts.emails + dd.counts.usernames : 0;
                return (
                  <button key={n} onClick={() => setActiveName(n)}
                    className={`border px-2.5 py-1.5 text-xs transition ${activeName === n ? "border-accent text-accent" : "border-line text-muted hover:text-ink"}`}>
                    {n} <span className="opacity-60">· {total}</span>
                  </button>
                );
              })}
            </div>
            {activeDossier ? <DossierView d={activeDossier} /> : <p className="text-sm text-muted">No data for this name yet.</p>}
          </>
        )}
      </section>
    </div>
  );
}

function PublicTab() {
  const [rows, setRows] = useState<SearchRow[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    try {
      const r = await api.get<{ searches: SearchRow[] }>("/discovery/public-searches");
      setRows(r.searches);
      setActive((cur) => cur ?? r.searches[0]?.term ?? null);
    } catch { /* */ } finally { setBusy(false); }
  }
  useEffect(() => { load(); }, []);

  async function clearAll() {
    if (!confirm("Clear the public search history?")) return;
    await api.del("/discovery/terms");
    setRows([]); setActive(null);
  }

  const activeRow = rows.find((r) => r.term === active);

  return (
    <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
      <section className="border border-line bg-panel-2 p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="kai-metadata uppercase">Public searches ({rows.length})</span>
          {rows.length > 0 && <button onClick={clearAll} className="flex items-center gap-1 text-[10px] text-muted hover:text-red-400"><Trash2 size={12} /> clear</button>}
        </div>
        {busy && rows.length === 0 ? <p className="text-sm text-muted">Loading…</p> :
          rows.length === 0 ? <p className="text-sm text-muted">No public searches recorded yet.</p> : (
            <div className="space-y-1">
              {rows.map((r) => (
                <button key={r.term} onClick={() => setActive(r.term)}
                  className={`flex w-full items-center justify-between border px-2.5 py-2 text-left text-xs transition ${active === r.term ? "border-accent" : "border-line hover:border-muted"}`}>
                  <span className="min-w-0 flex-1 truncate font-mono text-ink">{r.term}</span>
                  <span className="ml-2 shrink-0 kai-metadata">{r.kind} ·×{r.count}</span>
                  {r.pending && <span className="ml-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" title="discovery pending" />}
                </button>
              ))}
            </div>
          )}
      </section>
      <section className="border border-line bg-panel-2 p-4">
        {activeRow ? <DossierView d={activeRow.dossier} /> : <div className="flex h-full min-h-48 items-center justify-center text-sm text-muted">Select a search to see what KAI found.</div>}
      </section>
    </div>
  );
}
