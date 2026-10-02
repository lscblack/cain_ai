import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Globe, ImagePlus, Plus, ScanFace, ShieldCheck, Upload } from "lucide-react";
import { motion } from "framer-motion";

interface SearchMatch {
  face_id: string;
  similarity_pct: number;
  band: string;
  crop_url?: string | null;
  page_title?: string | null;
  source_url?: string | null;
  names?: string[];
}

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
const pub = (cropUrl?: string | null) =>
  cropUrl ? `${API_BASE}${cropUrl.replace("/intelligence/face/crop/", "/intelligence/face/public/crop/")}` : "";

function useObjectUrl(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) return setUrl(null);
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return url;
}

/** Hacker-style scanner: a grid of indexed faces rapidly flickering while a search runs. */
function FaceScanner({ active, pct }: { active: boolean; pct: number }) {
  const [crops, setCrops] = useState<string[]>([]);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    fetch(`${API_BASE}/intelligence/face/public/index-sample?limit=60`)
      .then((r) => r.json())
      .then((d) => setCrops((d.samples ?? []).map((s: any) => `${API_BASE}${s.crop_url}`)))
      .catch(() => setCrops([]));
  }, []);
  useEffect(() => {
    if (!active || crops.length === 0) return;
    const id = setInterval(() => setTick((t) => t + 1), 110);
    return () => clearInterval(id);
  }, [active, crops.length]);

  const cells = 18;
  return (
    <div className="relative overflow-hidden border border-line bg-panel-2">
      <div className="grid grid-cols-6 gap-px bg-line/40">
        {Array.from({ length: cells }).map((_, i) => {
          const src = crops.length ? crops[(tick * 3 + i * 7) % crops.length] : "";
          return (
            <div key={i} className="relative aspect-square overflow-hidden bg-panel">
              {src && (
                <motion.img
                  key={src + i}
                  src={src}
                  alt=""
                  initial={{ opacity: 0.15 }}
                  animate={{ opacity: active ? [0.2, 0.9, 0.2] : 0.25 }}
                  transition={{ duration: 0.5, repeat: active ? Infinity : 0, delay: (i % 6) * 0.04 }}
                  className="h-full w-full object-cover"
                />
              )}
            </div>
          );
        })}
      </div>
      {active && (
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute left-0 top-0 h-[2px] w-full bg-accent/80 shadow-[0_0_14px_var(--kai-accent)]"
               style={{ top: `${(pct || (tick * 7) % 100)}%`, transition: "top .2s linear" }} />
          <div className="absolute inset-0 border border-accent/30" />
        </div>
      )}
    </div>
  );
}

export function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const [scanned, setScanned] = useState<number | null>(null);
  const [indexed, setIndexed] = useState<number | null>(null);
  const [pct, setPct] = useState(0);
  const [stage, setStage] = useState("READY FOR INPUT");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const previewUrl = useObjectUrl(file);

  // website submission
  const [siteName, setSiteName] = useState("");
  const [siteUrl, setSiteUrl] = useState("");
  const [subMsg, setSubMsg] = useState<string | null>(null);
  const [subBusy, setSubBusy] = useState(false);

  function selectFile(next: File | null) {
    if (!next || !next.type.startsWith("image/")) return setError("Select a JPG, PNG, WEBP, or BMP image.");
    if (next.size > 12 * 1024 * 1024) return setError("Image must be smaller than 12 MB.");
    setFile(next); setMatches([]); setError(null); setDone(false); setStage("IMAGE READY");
  }

  async function search() {
    if (!file || busy) return;
    setBusy(true); setMatches([]); setScanned(null); setIndexed(null); setPct(0); setError(null); setDone(false);
    setStage("UPLOADING IMAGE");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(`${API_BASE}/intelligence/face/public/search/stream`, { method: "POST", body });
      if (!response.ok || !response.body) {
        setError(response.status === 503 ? "Face engine is offline." : "Search could not be completed.");
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const event = chunk.match(/event: (.*)/)?.[1];
          const line = chunk.match(/data: (.*)/)?.[1];
          if (!line) continue;
          const payload = JSON.parse(line);
          if (event === "stage") {
            setStage((payload.name ?? "SCANNING").replaceAll("_", " ").toUpperCase());
            if (payload.indexed != null) setIndexed(payload.indexed);
          } else if (event === "progress") {
            setScanned(payload.scanned ?? null);
            if (payload.total != null) { setIndexed(payload.total); setPct(Math.round(((payload.scanned ?? 0) / payload.total) * 100)); }
          } else if (event === "result") {
            setMatches(payload.matches ?? []); setStage("SEARCH COMPLETE"); setPct(100); setDone(true);
          } else if (event === "error") {
            setError(payload.detail ?? "Search failed.");
          }
        }
      }
    } catch {
      setError("Unable to reach the search service.");
    } finally {
      setBusy(false);
    }
  }

  async function submitSite(e: React.FormEvent) {
    e.preventDefault();
    if (!siteUrl.trim() || subBusy) return;
    setSubBusy(true); setSubMsg(null);
    try {
      const r = await fetch(`${API_BASE}/sources/public-submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: siteName.trim() || siteUrl.trim(), url: siteUrl.trim() }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.status === 201 && d.status === "created") setSubMsg(`✓ Added ${d.domain} to the crawl queue.`);
      else if (d.status === "exists") setSubMsg(`• ${d.domain} is already in the index.`);
      else if (r.status === 429) setSubMsg("Too many submissions — try again later.");
      else setSubMsg(typeof d.detail === "string" ? d.detail : "Could not add that website.");
      if (r.ok) { setSiteName(""); setSiteUrl(""); }
    } catch {
      setSubMsg("Could not reach the service.");
    } finally {
      setSubBusy(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-base text-ink">
      <div className="home-grid pointer-events-none absolute inset-0 opacity-40" aria-hidden="true" />

      <nav className="relative mx-auto flex w-11/12 max-w-[1700px] items-center justify-between py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center border border-accent/50 bg-panel text-accent shadow-[0_0_24px_rgba(229,72,77,0.18)]">
            <ScanFace size={19} />
          </div>
          <div>
            <div className="font-mono text-sm font-semibold tracking-[0.3em]">KAI</div>
            <div className="kai-metadata hidden sm:block">OPEN INTELLIGENCE TERMINAL</div>
          </div>
        </div>
        <Link to="/login" className="inline-flex items-center gap-2 border border-line bg-panel/70 px-3 py-2 font-mono text-xs text-muted transition hover:border-accent hover:text-ink">
          OPERATOR ACCESS <ArrowUpRight size={13} />
        </Link>
      </nav>

      <section className="relative mx-auto grid w-11/12 max-w-[1700px] gap-8 pb-14 pt-6 lg:grid-cols-[0.8fr_1.2fr] lg:items-center lg:gap-14 lg:pt-14">
        <div>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mb-5 flex items-center gap-2 font-mono text-xs tracking-[0.25em] text-accent">
            <span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> PUBLIC SEARCH NODE / 01
          </motion.div>
          <motion.h1 initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }} className="text-4xl font-semibold leading-[1.03] tracking-tight sm:text-5xl xl:text-6xl">
            Find the signal<br /><span className="text-accent">inside the image.</span>
          </motion.h1>
          <motion.p initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16 }} className="mt-6 max-w-lg text-base leading-7 text-muted sm:text-lg">
            Upload a face and scan it against KAI's indexed intelligence corpus. No account required.
          </motion.p>
          <div className="mt-8 flex flex-wrap gap-x-5 gap-y-2 font-mono text-[11px] uppercase tracking-wider text-muted">
            <span className="text-verified">● LOCAL INDEX</span><span>PRIVATE BY DEFAULT</span><span>PROVENANCE AWARE</span>
          </div>
        </div>

        <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.1 }} className="relative">
          <div className="absolute -inset-4 bg-accent/5 blur-3xl" aria-hidden="true" />
          <div className="relative grid gap-3 border border-line bg-panel/95 p-3 shadow-2xl sm:grid-cols-2 sm:p-4">
            {/* query / upload */}
            <div className="flex flex-col">
              <div className="flex items-center justify-between border-b border-line pb-2 font-mono text-[11px] uppercase tracking-wider text-muted">
                <span className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-verified" /> image query</span>
                <span className="text-accent">{stage}</span>
              </div>
              <button type="button" onClick={() => inputRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); selectFile(e.dataTransfer.files[0] ?? null); }}
                className="group mt-3 flex min-h-[220px] flex-1 items-center justify-center overflow-hidden border border-dashed border-line bg-panel-2 transition hover:border-accent/70">
                {previewUrl ? <img src={previewUrl} alt="query" className="h-full max-h-[320px] w-full object-contain" /> : (
                  <span className="flex flex-col items-center gap-3 px-6 text-center">
                    <span className="flex h-12 w-12 items-center justify-center border border-line bg-panel text-accent group-hover:border-accent"><ImagePlus size={22} /></span>
                    <span><strong className="block font-mono text-sm">DROP IMAGE</strong><small className="mt-1 block text-muted">or choose a file</small></span>
                  </span>
                )}
              </button>
              <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={(e) => selectFile(e.target.files?.[0] ?? null)} />
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={search} disabled={!file || busy} className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 bg-accent px-4 font-mono text-xs font-semibold tracking-wider text-white transition hover:brightness-110 disabled:opacity-40"><ScanFace size={16} /> {busy ? "SCANNING…" : "SEARCH IMAGE"}</button>
                <button type="button" onClick={() => inputRef.current?.click()} className="inline-flex min-h-11 items-center justify-center gap-2 border border-line px-3 font-mono text-xs text-muted hover:border-muted hover:text-ink"><Upload size={15} /></button>
              </div>
            </div>
            {/* live scanner */}
            <div className="flex flex-col">
              <div className="flex items-center justify-between border-b border-line pb-2 font-mono text-[11px] uppercase tracking-wider text-muted">
                <span>index scan</span>
                <span className="text-accent">{busy ? `${pct}%` : done ? "DONE" : "IDLE"}</span>
              </div>
              <div className="mt-3 flex-1"><FaceScanner active={busy} pct={pct} /></div>
              <div className="mt-2 font-mono text-[10px] text-muted">{scanned != null && indexed != null ? `${scanned} / ${indexed} compared` : "awaiting query"}</div>
            </div>
          </div>
          {error && <div className="mt-3 border border-accent/40 bg-accent/5 px-3 py-2 font-mono text-xs text-accent">{error}</div>}
        </motion.div>
      </section>

      {/* results */}
      <section className="relative mx-auto w-11/12 max-w-[1700px] pb-14">
        <div className="mb-4 flex items-end justify-between border-b border-line pb-3">
          <div className="font-mono text-xs uppercase tracking-[0.2em] text-muted">Query output</div>
          <div className="font-mono text-[11px] text-muted">{done ? `${matches.length} potential matches` : "awaiting input"}</div>
        </div>
        {matches.length === 0 ? (
          <div className="border border-line bg-panel/40 px-5 py-10 text-center font-mono text-xs uppercase tracking-wider text-muted">
            {done ? "No match found in current index" : "Submit an image to begin analysis"}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
            {matches.map((m) => (
              <motion.article key={m.face_id} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="overflow-hidden border border-line bg-panel">
                <div className="aspect-square bg-panel-2">{m.crop_url && <img src={pub(m.crop_url)} alt="match" className="h-full w-full object-cover" />}</div>
                <div className="p-3">
                  <div className="flex justify-between font-mono text-xs"><span className="text-accent">{m.similarity_pct}%</span><span className="text-muted">{m.band.replaceAll("_", " ")}</span></div>
                  <div className="mt-2 truncate text-sm">{m.names?.[0] ?? m.page_title ?? "Unattributed"}</div>
                  {m.source_url && <a href={m.source_url} target="_blank" rel="noreferrer" className="mt-1 block truncate font-mono text-[10px] text-muted hover:text-ink">{m.source_url}</a>}
                </div>
              </motion.article>
            ))}
          </div>
        )}
      </section>

      {/* public website submission */}
      <section className="relative mx-auto w-11/12 max-w-[1700px] pb-16">
        <div className="border border-line bg-panel/80 p-5 sm:p-7">
          <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.2em] text-accent"><Globe size={15} /> Contribute a source</div>
          <h2 className="mt-3 text-xl font-semibold sm:text-2xl">Add your website to the crawl index</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">Submit a public website and KAI will queue it for crawling. Duplicates are ignored automatically. Only submit sites you are permitted to index.</p>
          <form onSubmit={submitSite} className="mt-5 flex flex-col gap-2 sm:flex-row">
            <input value={siteName} onChange={(e) => setSiteName(e.target.value)} placeholder="Name (optional)" className="min-h-11 rounded-none border border-line bg-panel-2 px-3 font-mono text-sm outline-none focus:border-accent sm:w-56" />
            <input value={siteUrl} onChange={(e) => setSiteUrl(e.target.value)} required placeholder="example.com or https://example.com" className="min-h-11 flex-1 rounded-none border border-line bg-panel-2 px-3 font-mono text-sm outline-none focus:border-accent" />
            <button disabled={subBusy} className="inline-flex min-h-11 items-center justify-center gap-2 bg-accent px-5 font-mono text-xs font-semibold tracking-wider text-white transition hover:brightness-110 disabled:opacity-40"><Plus size={15} /> {subBusy ? "ADDING…" : "ADD SITE"}</button>
          </form>
          {subMsg && <div className="mt-3 font-mono text-xs" style={{ color: subMsg.startsWith("✓") ? "var(--kai-verified)" : "var(--kai-muted)" }}>{subMsg}</div>}
        </div>
      </section>

      <footer className="relative mx-auto flex w-11/12 max-w-[1700px] flex-col gap-3 border-t border-line py-6 font-mono text-[11px] text-muted sm:flex-row sm:items-center sm:justify-between">
        <span className="flex items-center gap-2"><ShieldCheck size={14} className="text-verified" /> RESULTS ARE SIMILARITY SIGNALS, NOT IDENTITY DETERMINATIONS</span>
        <span>KAI / KNOWLEDGE · ANALYSIS · INTELLIGENCE</span>
      </footer>
    </main>
  );
}
