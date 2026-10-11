import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Upload, ScanSearch, FolderPlus } from "lucide-react";

import { api } from "@/lib/api";
import { cropFace, type Bbox } from "@/lib/faceCrop";
import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

interface DetectedFace {
  bbox: Bbox;
  det_score: number;
  quality: number;
  embedding_dim: number;
  age: number | null;
  sex: string | null;
}
interface DetectResponse {
  image_hash: string;
  faces_detected: number;
  faces: DetectedFace[];
}
interface SearchMatch {
  face_id: string;
  similarity_pct: number;
  band: string;
  crop_url?: string | null;
  names?: string[];
  page_title?: string | null;
  source_url?: string | null;
  description?: string | null;
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
const BOX_COLORS = ["#4ea1ff", "#ffb020", "#36d399", "#f87272", "#a78bfa", "#f472b6"];

function imageFromDrop(e: React.DragEvent): File | null {
  const f = e.dataTransfer.files?.[0] ?? null;
  return f && f.type.startsWith("image/") ? f : null;
}

/** Multi-face detector: upload an image, see every face with its details,
 *  search any one face against the local index, or capture it to a case. */
export function MultiFaceDetect({ engineAvailable }: { engineAvailable: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [result, setResult] = useState<DetectResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [crops, setCrops] = useState<Record<number, string>>({});
  const [perFace, setPerFace] = useState<
    Record<number, { loading?: boolean; matches?: SearchMatch[]; captured?: string; error?: string }>
  >({});
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [caseId, setCaseId] = useState<string>("");

  const naturalImg = useRef<HTMLImageElement | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [natSize, setNatSize] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    investigationsApi.list().then(setCases).catch(() => setCases([]));
  }, []);

  useEffect(() => {
    if (!file) {
      setImgUrl(null);
      return;
    }
    const u = URL.createObjectURL(file);
    setImgUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  const choose = useCallback((f: File | null) => {
    setFile(f);
    setResult(null);
    setCrops({});
    setPerFace({});
    setError(null);
    setNatSize(null);
    naturalImg.current = null;
  }, []);

  async function makeCrops(faces: DetectedFace[]) {
    const img = naturalImg.current;
    if (!img || !natSize) return;
    const next: Record<number, string> = {};
    for (let i = 0; i < faces.length; i++) {
      try {
        const c = await cropFace(img, faces[i].bbox, {
          naturalWidth: natSize.w,
          naturalHeight: natSize.h,
        });
        next[i] = c.dataUrl;
      } catch {
        /* skip a crop that fails */
      }
    }
    setCrops(next);
  }

  async function runDetect() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setPerFace({});
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.postForm<DetectResponse>("/intelligence/face/detect", fd);
      setResult(r);
      await makeCrops(r.faces);
    } catch (e: any) {
      setError(
        e?.detail === "face_engine_unavailable" ? "FACE ENGINE UNAVAILABLE" : "Detection failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function searchFace(i: number) {
    if (!file) return;
    setPerFace((p) => ({ ...p, [i]: { ...p[i], loading: true, error: undefined } }));
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("face_index", String(i));
      fd.append("top_k", "6");
      const r = await api.postForm<{ matches: SearchMatch[]; detail?: string }>(
        "/intelligence/face/search",
        fd,
      );
      setPerFace((p) => ({ ...p, [i]: { matches: r.matches ?? [], loading: false } }));
    } catch {
      setPerFace((p) => ({ ...p, [i]: { ...p[i], loading: false, error: "Search failed." } }));
    }
  }

  async function captureFace(i: number, face: DetectedFace) {
    if (!caseId || !naturalImg.current || !natSize) return;
    setPerFace((p) => ({ ...p, [i]: { ...p[i], loading: true } }));
    try {
      const c = await cropFace(naturalImg.current, face.bbox, {
        naturalWidth: natSize.w,
        naturalHeight: natSize.h,
        maxSize: 512,
      });
      const fd = new FormData();
      fd.append("file", new File([c.blob], "face.jpg", { type: "image/jpeg" }));
      fd.append("investigation_id", caseId);
      fd.append("source_url", "upload:multi-face");
      await api.postForm("/intelligence/face/detect", fd);
      const name = cases.find((x) => x.id === caseId)?.name ?? "case";
      setPerFace((p) => ({ ...p, [i]: { ...p[i], loading: false, captured: name } }));
    } catch {
      setPerFace((p) => ({ ...p, [i]: { ...p[i], loading: false, error: "Capture failed." } }));
    }
  }

  const faces = result?.faces ?? [];

  return (
    <div>
      {!engineAvailable && (
        <div
          className="mb-4 rounded-md border px-3 py-2 text-sm"
          style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}
        >
          The face engine is unavailable on this host — detection is disabled.
        </div>
      )}

      <div className="grid gap-5 md:grid-cols-[360px_1fr]">
        {/* Upload + annotated image */}
        <div className="space-y-3">
          <div className="kai-metadata uppercase">Image</div>
          <div
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = imageFromDrop(e);
              if (f) choose(f);
            }}
            className="relative flex min-h-[220px] cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-dashed border-line bg-panel-2 transition hover:border-accent/70"
          >
            {imgUrl ? (
              <div className="relative inline-block w-full">
                <img
                  src={imgUrl}
                  alt="uploaded"
                  className="block w-full"
                  onLoad={(e) => {
                    const el = e.currentTarget;
                    naturalImg.current = el;
                    setNatSize({ w: el.naturalWidth, h: el.naturalHeight });
                  }}
                />
                {natSize &&
                  faces.map((f, i) => (
                    <div
                      key={i}
                      className="absolute flex items-start justify-start"
                      style={{
                        left: `${(f.bbox[0] / natSize.w) * 100}%`,
                        top: `${(f.bbox[1] / natSize.h) * 100}%`,
                        width: `${((f.bbox[2] - f.bbox[0]) / natSize.w) * 100}%`,
                        height: `${((f.bbox[3] - f.bbox[1]) / natSize.h) * 100}%`,
                        border: `2px solid ${BOX_COLORS[i % BOX_COLORS.length]}`,
                        boxShadow: "0 0 0 1px rgba(0,0,0,0.4)",
                      }}
                    >
                      <span
                        className="px-1 text-[10px] font-bold leading-tight text-black"
                        style={{ background: BOX_COLORS[i % BOX_COLORS.length] }}
                      >
                        {i + 1}
                      </span>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted">
                <Upload size={22} />
                <span className="text-xs">Upload an image with one or more faces</span>
                <span className="kai-metadata">drag · click</span>
              </div>
            )}
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
          />
          <button
            onClick={runDetect}
            disabled={loading || !file || !engineAvailable}
            className="w-full rounded-md border border-line bg-panel py-2 text-sm hover:bg-panel-2 disabled:opacity-50"
          >
            {loading ? "Detecting…" : "Detect faces"}
          </button>
          {error && (
            <div className="text-xs" style={{ color: "var(--kai-accent)" }}>
              {error}
            </div>
          )}

          <div className="kai-metadata uppercase pt-2">Capture to case</div>
          <select
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
            className="w-full rounded-md border border-line bg-panel px-2 py-1.5 text-sm"
          >
            <option value="">— select an investigation —</option>
            {cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>

        {/* Per-face cards */}
        <div>
          {result && (
            <div className="kai-metadata mb-3 uppercase" style={{ color: "var(--kai-verified)" }}>
              {result.faces_detected} face{result.faces_detected === 1 ? "" : "s"} detected
            </div>
          )}
          {result && faces.length === 0 && (
            <div
              className="rounded-lg border p-6 text-center"
              style={{ borderColor: "var(--kai-border)" }}
            >
              <div className="text-lg font-semibold" style={{ color: "var(--kai-muted)" }}>
                NO FACE DETECTED
              </div>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            {faces.map((f, i) => {
              const pf = perFace[i] ?? {};
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.04 }}
                  className="overflow-hidden rounded-lg border border-line bg-panel"
                >
                  <div className="flex gap-3 p-3">
                    <div
                      className="h-24 w-24 shrink-0 overflow-hidden rounded border"
                      style={{ borderColor: BOX_COLORS[i % BOX_COLORS.length] }}
                    >
                      {crops[i] ? (
                        <img src={crops[i]} alt={`face ${i + 1}`} className="h-full w-full object-cover" />
                      ) : (
                        <div className="h-full w-full bg-panel-2" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className="rounded px-1.5 text-xs font-bold text-black"
                          style={{ background: BOX_COLORS[i % BOX_COLORS.length] }}
                        >
                          #{i + 1}
                        </span>
                        <span className="kai-metadata">
                          q {Math.round(f.quality * 100)}% · det {Math.round(f.det_score * 100)}%
                        </span>
                      </div>
                      <div className="mt-1 text-sm">
                        {[f.sex, (f.age ?? 0) > 0 ? `~${f.age}y` : null].filter(Boolean).join(" · ") ||
                          "age/sex n/a"}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <button
                          onClick={() => searchFace(i)}
                          disabled={pf.loading}
                          className="flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel-2 disabled:opacity-50"
                        >
                          <ScanSearch size={13} /> Search this face
                        </button>
                        <button
                          onClick={() => captureFace(i, f)}
                          disabled={pf.loading || !caseId}
                          title={!caseId ? "Select an investigation first" : "Store this face in the case"}
                          className="flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel-2 disabled:opacity-50"
                        >
                          <FolderPlus size={13} /> Capture
                        </button>
                      </div>
                      {pf.captured && (
                        <div className="kai-metadata mt-1" style={{ color: "var(--kai-verified)" }}>
                          ✓ saved to {pf.captured}
                        </div>
                      )}
                      {pf.error && (
                        <div className="kai-metadata mt-1" style={{ color: "var(--kai-accent)" }}>
                          {pf.error}
                        </div>
                      )}
                    </div>
                  </div>

                  {pf.loading && <div className="kai-metadata px-3 pb-3">Working…</div>}
                  {pf.matches && (
                    <div className="border-t border-line px-3 py-2">
                      {pf.matches.length === 0 ? (
                        <div className="kai-metadata">No match in local index.</div>
                      ) : (
                        <div className="space-y-1.5">
                          {pf.matches.map((m) => (
                            <div key={m.face_id} className="flex items-center justify-between gap-2">
                              <span className="truncate text-xs">
                                {m.names?.[0] ?? m.page_title ?? m.source_url ?? m.face_id.slice(0, 8)}
                              </span>
                              <span className="flex shrink-0 items-center gap-2">
                                <span className="font-mono text-xs">{m.similarity_pct}%</span>
                                <span className="kai-metadata" style={{ color: BAND_COLOR[m.band] }}>
                                  {BAND_LABEL[m.band] ?? m.band}
                                </span>
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </motion.div>
              );
            })}
          </div>

          {!result && !loading && (
            <div className="text-sm text-muted">
              Upload an image and hit <span className="text-ink">Detect faces</span> to see every face,
              its age/sex estimate and quality, then search or capture each one.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
