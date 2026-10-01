import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ScanFace, Upload } from "lucide-react";

import { api } from "@/lib/api";

type Mode = "search" | "compare";

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

  const [matches, setMatches] = useState<SearchMatch[] | null>(null);
  const [compareResult, setCompareResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get<FaceStatus>("/intelligence/face/status").then(setStatus).catch(() => setStatus(null));
  }, []);

  async function runSearch() {
    if (!queryFile) return;
    setLoading(true);
    setError(null);
    setMatches(null);
    try {
      const fd = new FormData();
      fd.append("file", queryFile);
      const res = await api.postForm<{ matches: SearchMatch[] }>("/intelligence/face/search", fd);
      setMatches(res.matches);
    } catch (e: any) {
      setError(e?.detail === "face_engine_unavailable" ? "FACE ENGINE UNAVAILABLE" : "Search failed.");
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
        {(["search", "compare"] as Mode[]).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-2 text-sm capitalize ${mode === m ? "border-b-2 text-ink" : "text-muted"}`}
            style={mode === m ? { borderColor: "var(--kai-accent)" } : undefined}
          >
            {m === "search" ? "1:N Search" : "1:1 Compare"}
          </button>
        ))}
      </div>

      <div className="grid gap-5 md:grid-cols-[260px_1fr]">
        {/* Query face pinned on the left */}
        <div className="space-y-3">
          <div className="kai-metadata uppercase">Query face</div>
          <div
            onClick={() => queryInput.current?.click()}
            className="flex aspect-square cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-line bg-panel-2"
          >
            {queryUrl ? (
              <img src={queryUrl} alt="query" className="h-full w-full object-cover" />
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted">
                <Upload size={22} />
                <span className="text-xs">Upload a face</span>
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
              <label className="flex aspect-square cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-line bg-panel-2">
                {compareUrl ? (
                  <img src={compareUrl} alt="compare" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex flex-col items-center gap-2 text-muted">
                    <Upload size={22} />
                    <span className="text-xs">Second face</span>
                  </div>
                )}
                <input type="file" accept="image/*" hidden onChange={(e) => setCompareFile(e.target.files?.[0] ?? null)} />
              </label>
            </>
          )}

          <button
            onClick={mode === "search" ? runSearch : runCompare}
            disabled={loading || !queryFile || (mode === "compare" && !compareFile)}
            className="w-full rounded-md border border-line bg-panel py-2 text-sm hover:bg-panel-2 disabled:opacity-50"
          >
            {loading ? "Analyzing…" : mode === "search" ? "Search local index" : "Compare"}
          </button>
          {error && <div className="text-xs" style={{ color: "var(--kai-accent)" }}>{error}</div>}
        </div>

        {/* Results */}
        <div>
          {mode === "search" && matches && (
            <>
              <div className="kai-metadata mb-3 uppercase">
                {matches.length === 0 ? "No match found in current index" : `${matches.length} potential matches`}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {matches.map((m, i) => (
                  <motion.div
                    key={m.face_id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className="rounded-lg border border-line bg-panel p-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-lg">{m.similarity_pct}%</span>
                      <span className="kai-metadata" style={{ color: BAND_COLOR[m.band] }}>
                        {BAND_LABEL[m.band] ?? m.band}
                      </span>
                    </div>
                    <div className="kai-metadata mt-2 truncate">
                      {m.source_url ? (
                        <a href={m.source_url} target="_blank" rel="noreferrer" className="hover:text-ink">
                          {m.source_url}
                        </a>
                      ) : (
                        "no source url"
                      )}
                    </div>
                    <div className="kai-metadata mt-1">img {m.image_hash.slice(0, 12)}…</div>
                  </motion.div>
                ))}
              </div>
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

          {!matches && !compareResult && !loading && (
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
