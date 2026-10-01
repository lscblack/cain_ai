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

  async function remove(id: string) {
    await api.get(`/sources/${id}/stats`).catch(() => null);
    await fetchDelete(id);
    await load();
  }
  async function fetchDelete(id: string) {
    // delete has no body; reuse api via postForm-less fetch
    const token = localStorage.getItem("kai.token");
    await fetch(`${import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000"}/sources/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  }

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <Database size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Local Index — Sources</h1>
        <button onClick={load} className="ml-auto kai-metadata flex items-center gap-1 hover:text-ink">
          <RefreshCw size={13} /> refresh
        </button>
      </div>

      <form onSubmit={onCreate} className="mb-6 grid gap-2 rounded-lg border border-line bg-panel p-4 md:grid-cols-[1fr_1.5fr_auto_auto_auto]">
        <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Name" className="rounded-md border border-line bg-panel-2 px-3 py-2 text-sm" />
        <input value={url} onChange={(e) => setUrl(e.target.value)} required placeholder="https://example.com/" className="rounded-md border border-line bg-panel-2 px-3 py-2 text-sm" />
        <input type="number" min={0} max={5} value={depth} onChange={(e) => setDepth(+e.target.value)} title="depth" className="w-20 rounded-md border border-line bg-panel-2 px-2 py-2 text-sm" />
        <input type="number" min={1} max={5000} value={maxPages} onChange={(e) => setMaxPages(+e.target.value)} title="max pages" className="w-24 rounded-md border border-line bg-panel-2 px-2 py-2 text-sm" />
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
                <div>
                  <div className="font-medium">{s.name}</div>
                  <div className="kai-metadata">{s.base_url}</div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="kai-metadata uppercase" style={{ color }}>● {s.status}</span>
                  <button onClick={() => crawl(s.id)} className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs hover:bg-panel-2">
                    <Play size={12} /> Crawl now
                  </button>
                  <button onClick={() => remove(s.id)} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-panel-2" style={{ color: "var(--kai-accent)" }}>
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
              <div className="kai-metadata mt-3 flex gap-5">
                <span>pages {st?.pages ?? "—"}</span>
                <span>images {st?.images ?? "—"}</span>
                <span>faces {st?.faces ?? "—"}</span>
                <span>depth {s.max_depth} · max {s.max_pages}</span>
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
