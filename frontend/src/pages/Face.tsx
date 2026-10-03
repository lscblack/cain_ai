import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ScanFace, Upload } from "lucide-react";

import { api } from "@/lib/api";
import { AuthImg } from "@/components/AuthImg";
import { SourceFrame, type SourceContext } from "@/components/SourceFrame";
import { usePasteImage } from "@/lib/usePasteImage";

function imageFromDrop(e: React.DragEvent): File | null {
  const f = e.dataTransfer.files?.[0] ?? null;
  return f && f.type.startsWith("image/") ? f : null;
}

type Mode = "search" | "compare" | "discover";

interface FaceStatus {
  available: boolean;
  model: string;
  model_version: string;
  embedding_dim: number;
  indexed_faces: number;
}

interface SearchMatch {
  face_id: string;
  investigation_id: string | null;
  source_url: string | null;
  image_hash: string;
  similarity: number;
  similarity_pct: number;
  band: string;
  crop_url?: string | null;
  page_title?: string | null;
  caption?: string | null;
  names?: string[];
  image_url?: string | null;
  description?: string | null;
  age?: number | null;
  sex?: string | null;
}

const BAND_LABEL: Record<string, string> = {
  potential_match: "POTENTIAL MATCH",
  strong_similarity: "STRONG SIMILARITY",
  possible_association: "POSSIBLE ASSOCIATION",
  no_match: "NO MATCH",
};
const BAND_COLOR: Record<string, string> = {
  potential_match: "var(--kai-accent)",
  strong_similarity: "var(--kai-warn)",
  possible_association: "var(--kai-muted)",
  no_match: "var(--kai-muted)",
};

function useObjectUrl(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) return setUrl(null);
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  return url;
}

export function Face() {
  const [status, setStatus] = useState<FaceStatus | null>(null);
  const [mode, setMode] = useState<Mode>("search");

  const [queryFile, setQueryFile] = useState<File | null>(null);
  const [compareFile, setCompareFile] = useState<File | null>(null);
  const queryUrl = useObjectUrl(queryFile);
  const compareUrl = useObjectUrl(compareFile);

  // Paste (Ctrl/Cmd+V) an image → query slot, or the compare slot once a query exists.
  const onPasteImage = useCallback(
    (f: File) => {
      if (mode === "compare" && queryFile) setCompareFile(f);
      else setQueryFile(f);
    },
    [mode, queryFile],
  );
  usePasteImage(onPasteImage);

  const [matches, setMatches] = useState<SearchMatch[] | null>(null);
  const [compareResult, setCompareResult] = useState<any>(null);
  const [discoverResult, setDiscoverResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stages, setStages] = useState<string[]>([]);
  const [frameCtx, setFrameCtx] = useState<SourceContext | null>(null);
  const [scanCrops, setScanCrops] = useState<string[]>([]);
  const [scanTick, setScanTick] = useState(0);
  const [progressPct, setProgressPct] = useState(0);
  const queryInput = useRef<HTMLInputElement>(null);

  // shifting-image scanner animation while a search runs
  useEffect(() => {
    if (!(loading && mode === "search" && scanCrops.length)) return;
    const id = setInterval(() => setScanTick((t) => t + 1), 140);
    return () => clearInterval(id);
  }, [loading, mode, scanCrops.length]);

  useEffect(() => {
    api.get<FaceStatus>("/intelligence/face/status").then(setStatus).catch(() => setStatus(null));
  }, []);

  const STAGE_LABEL: Record<string, string> = {
    image_received: "Image received",
    faces_detected: "Face detected",
    embedding_ready: "Embedding generated",
    comparing: "Comparing against local index",
    ranking: "Re-ranking results",
  };

  async function runSearch() {
    if (!queryFile) return;
    setLoading(true);
    setError(null);
    setMatches(null);
    setStages([]);
    setProgressPct(0);
    // pull indexed crop thumbnails to animate the "scanning" strip
    try {
      const s = await api.get<{ samples: { crop_url: string }[] }>("/intelligence/face/index-sample?limit=60");
      setScanCrops(s.samples.map((x) => x.crop_url));
    } catch {
      setScanCrops([]);
    }
    try {
      const fd = new FormData();
      fd.append("file", queryFile);
      const base = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
      const token = localStorage.getItem("kai.token");
      const resp = await fetch(`${base}/intelligence/face/search/stream`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      if (!resp.ok || !resp.body) {
        setError(resp.status === 503 ? "FACE ENGINE UNAVAILABLE" : "Search failed.");
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const ev = chunk.match(/event: (.*)/)?.[1];
          const dataLine = chunk.match(/data: (.*)/)?.[1];
          if (!dataLine) continue;
          const payload = JSON.parse(dataLine);
          if (ev === "stage") {
            const label = STAGE_LABEL[payload.name] ?? payload.name;
            const detail = payload.count != null ? ` (${payload.count})` : payload.indexed != null ? ` (${payload.indexed} indexed)` : "";
            setStages((s) => [...s, label + detail]);
          } else if (ev === "progress") {
            if (payload.total) setProgressPct(Math.round((payload.scanned / payload.total) * 100));
          } else if (ev === "result") {
            setProgressPct(100);
            setMatches(payload.matches ?? []);
          } else if (ev === "error") {
            setError(payload.detail ?? "Search failed.");
          }
        }
      }
    } catch {
      setError("Search failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runDiscover() {
    if (!queryFile) return;
    setLoading(true);
    setError(null);
    setDiscoverResult(null);
    try {
      const fd = new FormData();
      fd.append("file", queryFile);
      setDiscoverResult(await api.postForm("/intelligence/face/discover", fd));
    } catch (e: any) {
      setError(e?.detail === "face_engine_unavailable" ? "FACE ENGINE UNAVAILABLE" : "Discovery failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runCompare() {
    if (!queryFile || !compareFile) return;
    setLoading(true);
    setError(null);
    setCompareResult(null);
    try {
      const fd = new FormData();
      fd.append("file_a", queryFile);
      fd.append("file_b", compareFile);
      setCompareResult(await api.postForm("/intelligence/face/compare", fd));
    } catch (e: any) {
      setError(e?.detail === "face_engine_unavailable" ? "FACE ENGINE UNAVAILABLE" : "Compare failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      {frameCtx && <SourceFrame ctx={frameCtx} onClose={() => setFrameCtx(null)} />}
      <div className="mb-4 flex items-center gap-3">
        <ScanFace size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Face Intelligence</h1>
        {status && (
          <span className="ml-auto kai-metadata">
            <span style={{ color: status.available ? "var(--kai-verified)" : "var(--kai-accent)" }}>
              {status.available ? "ENGINE ONLINE" : "ENGINE UNAVAILABLE"}
            </span>{" "}
            · {status.model} · {status.indexed_faces} indexed
          </span>
        )}
      </div>

      {status && !status.available && (
        <div className="mb-4 rounded-md border px-3 py-2 text-sm" style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}>
          The face engine (InsightFace model) is not available on this host. Face features are disabled.
        </div>
      )}

      <div className="mb-5 flex gap-2 border-b border-line">
        {(["search", "compare", "discover"] as Mode[]).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-2 text-sm capitalize ${mode === m ? "border-b-2 text-ink" : "text-muted"}`}
            style={mode === m ? { borderColor: "var(--kai-accent)" } : undefined}
          >
            {m === "search" ? "1:N Local Search" : m === "compare" ? "1:1 Compare" : "Global Discovery"}
          </button>
        ))}
      </div>

      <div className="grid gap-5 md:grid-cols-[260px_1fr]">
        {/* Query face pinned on the left */}
        <div className="space-y-3">
          <div className="kai-metadata uppercase">Query face</div>
          <div
            onClick={() => queryInput.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); const f = imageFromDrop(e); if (f) setQueryFile(f); }}
            className="flex aspect-square cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-dashed border-line bg-panel-2 transition hover:border-accent/70"
          >
            {queryUrl ? (
              <img src={queryUrl} alt="query" className="h-full w-full object-cover" />
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted">
                <Upload size={22} />
                <span className="text-xs">Upload a face</span>
                <span className="kai-metadata">drag · paste · click</span>
              </div>
            )}
          </div>
          <input
            ref={queryInput}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => setQueryFile(e.target.files?.[0] ?? null)}
          />

          {mode === "compare" && (
            <>
              <div className="kai-metadata uppercase">Compare against</div>
              <label
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); const f = imageFromDrop(e); if (f) setCompareFile(f); }}
                className="flex aspect-square cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-dashed border-line bg-panel-2 transition hover:border-accent/70"
              >
                {compareUrl ? (
                  <img src={compareUrl} alt="compare" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex flex-col items-center gap-2 text-muted">
                    <Upload size={22} />
                    <span className="text-xs">Second face</span>
                    <span className="kai-metadata">drag · paste · click</span>
                  </div>
                )}
                <input type="file" accept="image/*" hidden onChange={(e) => setCompareFile(e.target.files?.[0] ?? null)} />
              </label>
            </>
          )}

          <button
            onClick={mode === "search" ? runSearch : mode === "compare" ? runCompare : runDiscover}
            disabled={loading || !queryFile || (mode === "compare" && !compareFile)}
            className="w-full rounded-md border border-line bg-panel py-2 text-sm hover:bg-panel-2 disabled:opacity-50"
          >
            {loading ? "Analyzing…" : mode === "search" ? "Search local index" : mode === "compare" ? "Compare" : "Discover globally"}
          </button>
          {error && <div className="text-xs" style={{ color: "var(--kai-accent)" }}>{error}</div>}
        </div>

        {/* Results */}
        <div>
          {/* Live scanning animation: shifting indexed faces while comparing */}
          {mode === "search" && loading && (
            <div className="mb-5 rounded-lg border border-line bg-panel-2 p-4">
              <div className="mb-3 flex items-center justify-between">
                <span className="kai-metadata uppercase" style={{ color: "var(--kai-warn)" }}>
                  ● Scanning local index…
                </span>
                <span className="font-mono text-sm">{progressPct}%</span>
              </div>
              {scanCrops.length > 0 ? (
                <div className="flex gap-2 overflow-hidden">
                  {Array.from({ length: 8 }).map((_, i) => {
                    const idx = (scanTick + i) % scanCrops.length;
                    return (
                      <motion.div
                        key={i}
                        animate={{ opacity: [0.3, 1, 0.3] }}
                        transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.05 }}
                        className="h-16 w-16 shrink-0 overflow-hidden rounded border border-line"
                      >
                        <AuthImg path={scanCrops[idx]} className="h-full w-full object-cover" />
                      </motion.div>
                    );
                  })}
                </div>
              ) : (
                <div className="kai-metadata">No indexed face crops yet — index some via crawl or detect.</div>
              )}
              <div className="mt-3 h-1 w-full overflow-hidden rounded bg-panel">
                <div className="h-full" style={{ width: `${progressPct}%`, background: "var(--kai-accent)", transition: "width .2s" }} />
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5">
                {stages.map((s, i) => (
                  <span key={i} className="kai-metadata"><span style={{ color: "var(--kai-verified)" }}>✓</span> {s}</span>
                ))}
              </div>
            </div>
          )}

          {mode === "search" && matches && !loading && (
            <>
              {matches.length === 0 ? (
                <div className="rounded-lg border p-6 text-center" style={{ borderColor: "var(--kai-border)" }}>
                  <div className="text-lg font-semibold" style={{ color: "var(--kai-muted)" }}>NO MATCH FOUND</div>
                  <div className="kai-metadata mt-1">in the current local index</div>
                </div>
              ) : (
                <>
                  <div className="kai-metadata mb-3 uppercase" style={{ color: "var(--kai-verified)" }}>
                    {matches.length} potential match{matches.length > 1 ? "es" : ""} found
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {matches.map((m, i) => (
                      <motion.div
                        key={m.face_id}
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{ delay: i * 0.05 }}
                        className="overflow-hidden rounded-lg border border-line bg-panel"
                      >
                        <div className="flex">
                          {m.crop_url && <AuthImg path={m.crop_url} className="h-28 w-28 shrink-0 object-cover" />}
                          <div className="min-w-0 flex-1 p-3">
                            <div className="flex items-center justify-between">
                              <span className="font-mono text-lg">{m.similarity_pct}%</span>
                              <span className="kai-metadata" style={{ color: BAND_COLOR[m.band] }}>
                                {BAND_LABEL[m.band] ?? m.band}
                              </span>
                            </div>
                            {(m.names?.[0] || m.page_title) && <div className="mt-1 truncate text-sm font-semibold">{m.names?.[0] ?? m.page_title}</div>}
                            {(m.sex || (m.age ?? 0) > 0) && (
                              <div className="kai-metadata mt-0.5">{[m.sex, (m.age ?? 0) > 0 ? `~${m.age}y` : null].filter(Boolean).join(" · ")}</div>
                            )}
                            {m.description && (
                              <div className="mt-2 border-l-2 px-2 py-1.5 font-mono text-[11px] leading-relaxed" style={{ borderColor: "var(--kai-accent)", background: "var(--kai-panel-2)", color: "var(--kai-muted)" }}>
                                {m.description}
                              </div>
                            )}
                            {m.names && m.names.length > 1 && (
                              <div className="mt-2 flex flex-wrap gap-1">
                                {m.names.slice(1, 4).map((n) => (
                                  <span key={n} className="rounded border border-line px-1.5 py-0.5 text-xs" style={{ color: "var(--kai-warn)" }}>{n}</span>
                                ))}
                              </div>
                            )}
                            {m.source_url && (
                              <>
                                <a href={m.source_url} target="_blank" rel="noreferrer" title={m.source_url} className="kai-metadata mt-2 block truncate hover:text-ink">found on: {m.source_url}</a>
                                <div className="mt-2 flex gap-2">
                                  <button
                                    onClick={() => setFrameCtx({ url: m.source_url!, title: m.page_title, caption: m.caption, names: m.names, imageUrl: m.image_url })}
                                    className="rounded border border-line px-2 py-1 text-xs hover:bg-panel-2"
                                  >
                                    Open in frame
                                  </button>
                                  <a href={m.source_url} target="_blank" rel="noreferrer" className="rounded border border-line px-2 py-1 text-xs hover:bg-panel-2">
                                    Read more ↗
                                  </a>
                                </div>
                              </>
                            )}
                          </div>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}

          {mode === "compare" && compareResult && (
            <div className="rounded-lg border border-line bg-panel p-5">
              {compareResult.comparable ? (
                <>
                  <div className="font-mono text-4xl">{compareResult.similarity_pct}%</div>
                  <div className="mt-2 kai-metadata uppercase" style={{ color: BAND_COLOR[compareResult.band] }}>
                    {BAND_LABEL[compareResult.band] ?? compareResult.band}
                  </div>
                  <div className="kai-metadata mt-4 border-t border-line pt-3" style={{ color: "var(--kai-warn)" }}>
                    {compareResult.note}
                  </div>
                </>
              ) : (
                <div className="text-sm text-muted">No face detected in one or both images.</div>
              )}
            </div>
          )}

          {mode === "discover" && discoverResult && !loading && (
            <div>
              {discoverResult.available === false ? (
                <div className="rounded-lg border border-line bg-panel p-4 text-sm">
                  <div className="kai-metadata uppercase" style={{ color: "var(--kai-warn)" }}>
                    provider unavailable
                  </div>
                  <div className="mt-2 text-muted">{discoverResult.hint}</div>
                </div>
              ) : (
                <>
                  <div className="kai-metadata mb-3 uppercase">
                    {discoverResult.matches?.length
                      ? `${discoverResult.matches.length} verified matches`
                      : "No verified matches among candidates"}
                    {" · "}{discoverResult.candidates_downloaded} downloaded · {discoverResult.duplicates_skipped} dupes
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {(discoverResult.matches ?? []).map((m: any, i: number) => (
                      <div key={i} className="rounded-lg border border-line bg-panel p-3">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-lg">{m.similarity_pct}%</span>
                          <span className="kai-metadata" style={{ color: BAND_COLOR[m.band] }}>
                            {BAND_LABEL[m.band] ?? m.band}
                          </span>
                        </div>
                        <a href={m.source_url} target="_blank" rel="noreferrer" className="kai-metadata mt-2 block truncate hover:text-ink">
                          {m.source_url}
                        </a>
                        <div className="kai-metadata mt-1">{m.provider}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {!matches && !compareResult && !discoverResult && !loading && (
            <div className="text-sm text-muted">
              {mode === "search"
                ? "Upload a face to search KAI's local face index."
                : "Upload two faces to compare their similarity."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
