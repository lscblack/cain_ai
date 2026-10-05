import { useEffect, useState, type FormEvent } from "react";
import { Database, Play, Trash2, RefreshCw } from "lucide-react";

import { api } from "@/lib/api";

interface Source {
  id: string;
  name: string;
  base_url: string;
  domain: string;
  max_depth: number;
  max_pages: number;
  schedule: string;
  status: string;
  category: string | null;
  priority: string | null;
  last_crawled_at: string | null;
  last_error: string | null;
}
interface Stats {
  source_id: string;
  pages: number;
  images: number;
  faces: number;
  status: string;
  last_crawled_at: string | null;
}

export function Sources() {
  const [sources, setSources] = useState<Source[]>([]);
  const [stats, setStats] = useState<Record<string, Stats>>({});
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [depth, setDepth] = useState(1);
  const [maxPages, setMaxPages] = useState(50);
  const [error, setError] = useState<string | null>(null);
  const [bulkText, setBulkText] = useState("");
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const [showBulk, setShowBulk] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [allDepth, setAllDepth] = useState(1);
  const [allPages, setAllPages] = useState(50);
  const [allSchedule, setAllSchedule] = useState("");
  const [applyMsg, setApplyMsg] = useState<string | null>(null);

  async function applyToAll() {
    const payload: Record<string, any> = { max_depth: allDepth, max_pages: allPages };
    if (allSchedule) payload.schedule = allSchedule;
    if (!confirm(`Apply depth=${allDepth}, max pages=${allPages}${allSchedule ? `, schedule=${allSchedule}` : ""} to ALL sources?`)) return;
    try {
      const r = await api.post<{ updated: number }>("/sources/bulk-update", payload);
      setApplyMsg(`Updated ${r.updated} source(s).`);
      await load();
    } catch (e: any) {
      setApplyMsg(`Bulk update failed${e?.detail ? `: ${e.detail}` : " (backend unreachable?)"}.`);
    }
  }

  async function onBulk() {
    if (!bulkText.trim()) return;
    setBulkMsg(null);
    try {
      const res = await api.post<{ created: any[]; errors: any[] }>("/sources/bulk", { csv: bulkText });
      setBulkMsg(`Added ${res.created.length} source(s), ${res.errors.length} error(s).`);
      setBulkText("");
      await load();
    } catch {
      setBulkMsg("Bulk add failed.");
    }
  }

  async function load() {
    const list = await api.get<Source[]>("/sources").catch(() => []);
    setSources(list);
    const s: Record<string, Stats> = {};
    await Promise.all(
      list.map(async (src) => {
        s[src.id] = await api.get<Stats>(`/sources/${src.id}/stats`).catch(() => s[src.id]);
      }),
    );
    setStats(s);
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 8000); // refresh stats/status
    return () => clearInterval(id);
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/sources", {
        name: name.trim(),
        base_url: url.trim(),
        max_depth: depth,
        max_pages: maxPages,
      });
      setName("");
      setUrl("");
      await load();
    } catch (err: any) {
      setError(err?.detail?.includes?.("unsafe") ? "That URL is not allowed (SSRF protection)." : "Failed to add source.");
    }
  }

  async function crawl(id: string) {
    await api.post(`/sources/${id}/crawl`).catch(() => null);
    setTimeout(load, 1500);
  }

  async function crawlAll() {
    if (!confirm(`Start crawling all ${sources.length} source(s)? This runs in the background (2 at a time).`)) return;
    const r = await api.post<{ scheduled: number }>("/sources/crawl-all").catch(() => null);
    if (r) {
      setApplyMsg(`Crawl started for ${r.scheduled} source(s). Watch the status/stats update below.`);
      setTimeout(load, 2000);
    }
  }

  async function seedDefaults() {
    if (!confirm("Seed the curated default source list (150+ domains)?")) return;
    const r = await api.post<{ created: number; skipped: number }>("/sources/seed-defaults").catch(() => null);
    if (r) {
      setBulkMsg(`Seeded ${r.created} default source(s), ${r.skipped} already present.`);
      await load();
    }
  }

  async function saveEdit(id: string, patch: Record<string, unknown>) {
    await api.get("/sources").catch(() => null); // noop keep-alive
    try {
      await (await fetch(`${import.meta.env.VITE_API_URL ?? "/api"}/sources/${id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("kai.token") ?? ""}`,
        },
        body: JSON.stringify(patch),
      })).json();
      setEditId(null);
      await load();
    } catch {
      /* ignore */
    }
  }

  async function remove(id: string) {
    await api.get(`/sources/${id}/stats`).catch(() => null);
    await fetchDelete(id);
    await load();
  }
  async function fetchDelete(id: string) {
    // delete has no body; reuse api via postForm-less fetch
    const token = localStorage.getItem("kai.token");
    await fetch(`${import.meta.env.VITE_API_URL ?? "/api"}/sources/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  }

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <Database size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Local Index — Sources</h1>
        <button onClick={crawlAll} className="ml-auto rounded-md border px-3 py-1.5 text-xs hover:bg-panel-2" style={{ borderColor: "var(--kai-verified)", color: "var(--kai-verified)" }}>
          ▶ Crawl all
        </button>
        <button onClick={seedDefaults} className="rounded-md border border-line px-3 py-1.5 text-xs hover:bg-panel-2">
          Seed default sources
        </button>
        <button onClick={load} className="kai-metadata flex items-center gap-1 hover:text-ink">
          <RefreshCw size={13} /> refresh
        </button>
      </div>
      <div className="mb-3 kai-metadata">{sources.length} source(s)</div>

      {/* Apply crawl settings to ALL sources at once */}
      <div className="mb-6 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel p-3">
        <span className="kai-metadata uppercase">Apply to all</span>
        <label className="kai-metadata flex items-center gap-1">
          depth
          <input type="number" min={0} max={20} value={allDepth} onChange={(e) => setAllDepth(Math.max(0, Math.min(20, +e.target.value)))} className="w-16 rounded border border-line bg-panel-2 px-2 py-1 text-sm" />
        </label>
        <label className="kai-metadata flex items-center gap-1">
          max pages
          <input type="number" min={1} max={1000000} value={allPages} onChange={(e) => setAllPages(Math.max(1, Math.min(1000000, +e.target.value)))} className="w-24 rounded border border-line bg-panel-2 px-2 py-1 text-sm" />
        </label>
        <label className="kai-metadata flex items-center gap-1">
          schedule
          <select value={allSchedule} onChange={(e) => setAllSchedule(e.target.value)} className="rounded border border-line bg-panel-2 px-2 py-1 text-sm">
            {["", "manual", "hourly", "6h", "daily", "weekly"].map((o) => <option key={o} value={o}>{o || "unchanged"}</option>)}
          </select>
        </label>
        <button onClick={applyToAll} className="rounded-md border border-line bg-panel-2 px-4 py-1.5 text-sm hover:bg-base">
          Apply to all {sources.length}
        </button>
        {applyMsg && <span className="kai-metadata" style={{ color: "var(--kai-verified)" }}>{applyMsg}</span>}
      </div>

      <form onSubmit={onCreate} className="mb-6 grid gap-2 rounded-lg border border-line bg-panel p-4 md:grid-cols-[1fr_1.5fr_auto_auto_auto]">
        <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Name" className="rounded-md border border-line bg-panel-2 px-3 py-2 text-sm" />
        <input value={url} onChange={(e) => setUrl(e.target.value)} required placeholder="https://example.com/" className="rounded-md border border-line bg-panel-2 px-3 py-2 text-sm" />
        <input type="number" min={0} max={20} value={depth} onChange={(e) => setDepth(+e.target.value)} title="depth" className="w-20 rounded-md border border-line bg-panel-2 px-2 py-2 text-sm" />
        <input type="number" min={1} max={1000000} value={maxPages} onChange={(e) => setMaxPages(+e.target.value)} title="max pages" className="w-24 rounded-md border border-line bg-panel-2 px-2 py-2 text-sm" />
        <button className="rounded-md border border-line bg-panel-2 px-4 py-2 text-sm hover:bg-base">Add source</button>
      </form>
      {error && <div className="mb-4 text-sm" style={{ color: "var(--kai-accent)" }}>{error}</div>}

      <div className="mb-6">
        <button onClick={() => setShowBulk((v) => !v)} className="kai-metadata hover:text-ink">
          {showBulk ? "▾" : "▸"} Bulk add / paste (CSV)
        </button>
        {showBulk && (
          <div className="mt-2 rounded-lg border border-line bg-panel p-4">
            <div className="kai-metadata mb-2">
              One per line: <span className="font-mono">name,base_url,max_depth,max_pages,schedule</span>
              {" "}— bare domains ok, header row optional.
            </div>
            <textarea
              value={bulkText}
              onChange={(e) => setBulkText(e.target.value)}
              rows={6}
              placeholder={"Rwanda News,https://example.rw/,1,50,daily\nKT Press,ktpress.rw\nThe New Times,newtimes.co.rw,2,100"}
              className="w-full rounded-md border border-line bg-panel-2 px-3 py-2 font-mono text-xs outline-none focus:border-muted"
            />
            <div className="mt-2 flex items-center gap-3">
              <button onClick={onBulk} className="rounded-md border border-line bg-panel-2 px-4 py-2 text-sm hover:bg-base">
                Add all
              </button>
              {bulkMsg && <span className="kai-metadata" style={{ color: "var(--kai-verified)" }}>{bulkMsg}</span>}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-3">
        {sources.length === 0 && <div className="text-sm text-muted">No sources. Add a permitted public domain to start building the local index.</div>}
        {sources.map((s) => {
          const st = stats[s.id];
          const color = s.status === "crawling" ? "var(--kai-warn)" : s.status === "error" ? "var(--kai-accent)" : "var(--kai-verified)";
          return (
            <div key={s.id} className="rounded-lg border border-line bg-panel p-4">
              <div className="flex items-center justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{s.name}</span>
                    {s.priority && (
                      <span className="kai-metadata uppercase" style={{ color: s.priority === "high" ? "var(--kai-accent)" : s.priority === "medium" ? "var(--kai-warn)" : "var(--kai-muted)" }}>
                        {s.priority}
                      </span>
                    )}
                    {s.category && <span className="kai-metadata">· {s.category}</span>}
                  </div>
                  <div className="kai-metadata">{s.base_url}</div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="kai-metadata uppercase" style={{ color }}>● {s.status}</span>
                  <button onClick={() => { setEditId(editId === s.id ? null : s.id); setDraft({ name: s.name, max_depth: s.max_depth, max_pages: s.max_pages, schedule: s.schedule, priority: s.priority ?? "" }); }} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-panel-2">
                    Edit
                  </button>
                  <button onClick={() => crawl(s.id)} className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs hover:bg-panel-2">
                    <Play size={12} /> Crawl now
                  </button>
                  <button onClick={() => remove(s.id)} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-panel-2" style={{ color: "var(--kai-accent)" }}>
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>

              {editId === s.id && (
                <div className="mt-3 grid gap-2 rounded-md border border-line bg-panel-2 p-3 md:grid-cols-[1.5fr_auto_auto_auto_auto_auto]">
                  <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="rounded border border-line bg-panel px-2 py-1 text-sm" />
                  <input type="number" min={0} max={20} value={draft.max_depth} onChange={(e) => setDraft({ ...draft, max_depth: +e.target.value })} title="depth" className="w-16 rounded border border-line bg-panel px-2 py-1 text-sm" />
                  <input type="number" min={1} max={1000000} value={draft.max_pages} onChange={(e) => setDraft({ ...draft, max_pages: +e.target.value })} title="max pages" className="w-20 rounded border border-line bg-panel px-2 py-1 text-sm" />
                  <select value={draft.schedule} onChange={(e) => setDraft({ ...draft, schedule: e.target.value })} className="rounded border border-line bg-panel px-2 py-1 text-sm">
                    {["manual", "hourly", "6h", "daily", "weekly"].map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                  <select value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })} className="rounded border border-line bg-panel px-2 py-1 text-sm">
                    {["", "high", "medium", "low"].map((o) => <option key={o} value={o}>{o || "priority"}</option>)}
                  </select>
                  <button onClick={() => saveEdit(s.id, { ...draft, priority: draft.priority || undefined })} className="rounded border border-line bg-panel px-3 py-1 text-sm hover:bg-base" style={{ color: "var(--kai-verified)" }}>Save</button>
                </div>
              )}

              <div className="kai-metadata mt-3 flex gap-5">
                <span>pages {st?.pages ?? "—"}</span>
                <span>images {st?.images ?? "—"}</span>
                <span>faces {st?.faces ?? "—"}</span>
                <span>depth {s.max_depth} · max {s.max_pages} · {s.schedule}</span>
                {s.last_crawled_at && <span>last {new Date(s.last_crawled_at).toLocaleTimeString()}</span>}
              </div>
              {s.last_error && <div className="kai-metadata mt-1" style={{ color: "var(--kai-accent)" }}>{s.last_error}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
