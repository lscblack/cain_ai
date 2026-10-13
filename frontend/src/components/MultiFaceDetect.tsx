import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Upload, FolderPlus, ExternalLink } from "lucide-react";

import { api } from "@/lib/api";
import { AuthImg } from "@/components/AuthImg";
import { ScanningStrip } from "@/components/ScanningStrip";
import { cropFace, type Bbox } from "@/lib/faceCrop";
import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

interface DetectedFace {
  bbox: Bbox;
  det_score: number;
  quality: number;
  age: number | null;
  sex: string | null;
}
interface Appearance {
  face_id: string;
  crop_url?: string | null;
  source_url?: string | null;
  page_title?: string | null;
  similarity_pct: number;
  band: string;
}
interface Person {
  person_id: string;
  name?: string | null;
  names?: string[];
  crop_url?: string | null;
  similarity_pct: number;
  band: string;
  appearance_count: number;
  appearances: Appearance[];
  age?: number | null;
  sex?: string | null;
}
interface FaceResult {
  face_index: number;
  bbox: Bbox;
  age: number | null;
  sex: string | null;
  quality: number;
  det_score: number;
  match_count: number;
  people: Person[];
}

const BAND_LABEL: Record<string, string> = {
  potential_match: "POTENTIAL MATCH",
  strong_similarity: "STRONG SIMILARITY",
  possible_association: "POSSIBLE ASSOCIATION",
  no_match: "NO MATCH",
};
const BAND_COLOR: Record<string, string> = {
  potential_match: "var(--kai-hud)",
  strong_similarity: "var(--kai-warn)",
  possible_association: "var(--kai-muted)",
  no_match: "var(--kai-muted)",
};
const BOX_COLORS = ["#22d3ee", "#ffb020", "#36d399", "#f87272", "#a78bfa", "#f472b6", "#4ea1ff"];

function imageFromDrop(e: React.DragEvent): File | null {
  const f = e.dataTransfer.files?.[0] ?? null;
  return f && f.type.startsWith("image/") ? f : null;
}

/** Multi-face detector: upload an image → every face is boxed, then each face is
 *  AUTOMATICALLY searched against the index (per-face scanning animation),
 *  showing matched images, not just text. Capture any face to a case. */
export function MultiFaceDetect({ engineAvailable }: { engineAvailable: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [faces, setFaces] = useState<DetectedFace[] | null>(null);
  const [crops, setCrops] = useState<Record<number, string>>({});
  const [peopleByIdx, setPeopleByIdx] = useState<Record<number, Person[]>>({});
  const [indexedCount, setIndexedCount] = useState<number | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanCrops, setScanCrops] = useState<string[]>([]);
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [caseId, setCaseId] = useState<string>("");
  const [captured, setCaptured] = useState<Record<number, string>>({});

  const naturalImg = useRef<HTMLImageElement | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [natSize, setNatSize] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    investigationsApi.list().then(setCases).catch(() => setCases([]));
    api
      .get<{ samples: { crop_url: string }[] }>("/intelligence/face/index-sample?limit=48")
      .then((s) => setScanCrops(s.samples.map((x) => x.crop_url)))
      .catch(() => setScanCrops([]));
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

  // Auto-run detect + search once the image is loaded (no manual clicking).
  const autoKey = useRef<string | null>(null);
  useEffect(() => {
    if (file && natSize && faces === null && !detecting && !searching && engineAvailable) {
      const key = `${file.name}-${file.size}`;
      if (autoKey.current !== key) {
        autoKey.current = key;
        void run();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, natSize, faces, detecting, searching, engineAvailable]);

  const choose = useCallback((f: File | null) => {
    autoKey.current = null;
    setFile(f);
    setFaces(null);
    setCrops({});
    setPeopleByIdx({});
    setCaptured({});
    setError(null);
    setNatSize(null);
    naturalImg.current = null;
  }, []);

  async function makeCrops(dfaces: DetectedFace[]) {
    const img = naturalImg.current;
    if (!img || !natSize) return;
    const next: Record<number, string> = {};
    for (let i = 0; i < dfaces.length; i++) {
      try {
        const c = await cropFace(img, dfaces[i].bbox, {
          naturalWidth: natSize.w,
          naturalHeight: natSize.h,
        });
        next[i] = c.dataUrl;
      } catch {
        /* skip */
      }
    }
    setCrops(next);
  }

  // Detect faces (fast, for boxes) then auto-search ALL of them in one call.
  async function run() {
    if (!file) return;
    setError(null);
    setFaces(null);
    setPeopleByIdx({});
    setCaptured({});

    // 1) detect → show faces + boxes immediately
    setDetecting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.postForm<{ faces: DetectedFace[] }>("/intelligence/face/detect", fd);
      setFaces(r.faces);
      await makeCrops(r.faces);
      if (r.faces.length === 0) return;
    } catch (e: any) {
      setError(e?.detail === "face_engine_unavailable" ? "FACE ENGINE UNAVAILABLE" : "Detection failed.");
      return;
    } finally {
      setDetecting(false);
    }

    // 2) auto-search every face (per-face scanning animation shows meanwhile)
    setSearching(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("all_faces", "true");
      fd.append("top_k", "8");
      const r = await api.postForm<{ faces: FaceResult[]; indexed_faces: number }>(
        "/intelligence/face/search",
        fd,
      );
      setIndexedCount(r.indexed_faces ?? 0);
      const map: Record<number, Person[]> = {};
      for (const fr of r.faces ?? []) map[fr.face_index] = fr.people ?? [];
      setPeopleByIdx(map);
    } catch {
      setError("Search failed.");
    } finally {
      setSearching(false);
    }
  }

  async function captureFace(i: number, face: DetectedFace) {
    if (!caseId || !naturalImg.current || !natSize) return;
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
      setCaptured((p) => ({ ...p, [i]: name }));
    } catch {
      setCaptured((p) => ({ ...p, [i]: "capture failed" }));
    }
  }

  const list = faces ?? [];

  return (
    <div>
      {!engineAvailable && (
        <div className="mb-4 rounded-md border px-3 py-2 text-sm" style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}>
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
            onDrop={(e) => { e.preventDefault(); const f = imageFromDrop(e); if (f) choose(f); }}
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
                  list.map((f, i) => (
                    <div
                      key={i}
                      className="absolute flex items-start justify-start"
                      style={{
                        left: `${(f.bbox[0] / natSize.w) * 100}%`,
                        top: `${(f.bbox[1] / natSize.h) * 100}%`,
                        width: `${((f.bbox[2] - f.bbox[0]) / natSize.w) * 100}%`,
                        height: `${((f.bbox[3] - f.bbox[1]) / natSize.h) * 100}%`,
                        border: `2px solid ${BOX_COLORS[i % BOX_COLORS.length]}`,
                        boxShadow: "0 0 8px rgba(34,211,238,0.4)",
                      }}
                    >
                      <span className="px-1 text-[10px] font-bold leading-tight text-black" style={{ background: BOX_COLORS[i % BOX_COLORS.length] }}>
                        {i + 1}
                      </span>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted">
                <Upload size={22} />
                <span className="text-xs">Upload an image with one or more faces</span>
                <span className="kai-metadata">drag · click · auto-searches each face</span>
              </div>
            )}
          </div>
          <input ref={fileInput} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0] ?? null; choose(f); }} />
          <button
            onClick={run}
            disabled={detecting || searching || !file || !engineAvailable}
            className="w-full rounded-md border py-2 text-sm hud-mono uppercase tracking-wider disabled:opacity-50"
            style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)", background: "rgba(34,211,238,0.06)" }}
          >
            {detecting ? "Detecting…" : searching ? "Scanning all faces…" : "Detect & search all faces"}
          </button>
          {error && <div className="text-xs" style={{ color: "var(--kai-accent)" }}>{error}</div>}

          <div className="kai-metadata uppercase pt-2">Capture to case</div>
          <select value={caseId} onChange={(e) => setCaseId(e.target.value)} className="w-full rounded-md border border-line bg-panel px-2 py-1.5 text-sm">
            <option value="">— select an investigation —</option>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>

        {/* Per-face results */}
        <div>
          {faces && (
            <div className="hud-mono mb-3 text-xs uppercase hud-glow" style={{ color: "var(--kai-hud)" }}>
              ◢ {faces.length} face{faces.length === 1 ? "" : "s"} detected
              {searching ? " · scanning the index…" : indexedCount !== null ? ` · ${indexedCount} indexed` : ""}
            </div>
          )}
          {faces && faces.length === 0 && (
            <div className="rounded-lg border p-6 text-center" style={{ borderColor: "var(--kai-border)" }}>
              <div className="text-lg font-semibold" style={{ color: "var(--kai-muted)" }}>NO FACE DETECTED</div>
            </div>
          )}

          <div className="space-y-3">
            {list.map((f, i) => {
              const people = peopleByIdx[i];
              const color = BOX_COLORS[i % BOX_COLORS.length];
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.04 }}
                  className="hud-panel hud-frame p-3"
                >
                  <div className="flex gap-3">
                    <div className="h-24 w-24 shrink-0 overflow-hidden rounded border" style={{ borderColor: color }}>
                      {crops[i] ? <img src={crops[i]} alt={`face ${i + 1}`} className="h-full w-full object-cover" /> : <div className="h-full w-full bg-panel-2" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="rounded px-1.5 text-xs font-bold text-black" style={{ background: color }}>#{i + 1}</span>
                        <span className="text-sm">{[f.sex, (f.age ?? 0) > 0 ? `~${f.age}y` : null].filter(Boolean).join(" · ") || "age/sex n/a"}</span>
                        <span className="kai-metadata">q {Math.round(f.quality * 100)}% · det {Math.round(f.det_score * 100)}%</span>
                        <button
                          onClick={() => captureFace(i, f)}
                          disabled={!caseId}
                          title={!caseId ? "Select an investigation first" : "Store this face in the case"}
                          className="ml-auto flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs hover:bg-panel-2 disabled:opacity-50"
                        >
                          <FolderPlus size={12} /> Capture
                        </button>
                      </div>
                      {captured[i] && <div className="kai-metadata mt-1" style={{ color: "var(--kai-verified)" }}>✓ saved to {captured[i]}</div>}

                      {/* results — images, not just text */}
                      <div className="mt-2">
                        {!people ? (
                          <ScanningStrip crops={scanCrops} label="searching index…" />
                        ) : people.length === 0 ? (
                          <div className="kai-metadata">No match in local index.</div>
                        ) : (
                          <div className="flex gap-2 overflow-x-auto pb-1">
                            {people.map((p) => (
                              <a
                                key={p.person_id}
                                href={p.appearances[0]?.source_url ?? undefined}
                                target={p.appearances[0]?.source_url ? "_blank" : undefined}
                                rel="noreferrer"
                                className="w-28 shrink-0 overflow-hidden rounded border bg-panel"
                                style={{ borderColor: BAND_COLOR[p.band] }}
                                title={p.name ?? ""}
                              >
                                <div className="h-28 w-28">
                                  {p.crop_url ? (
                                    <AuthImg path={p.crop_url} className="h-full w-full object-cover" />
                                  ) : (
                                    <div className="flex h-full w-full items-center justify-center bg-panel-2 text-muted">?</div>
                                  )}
                                </div>
                                <div className="p-1.5">
                                  <div className="flex items-center justify-between">
                                    <span className="font-mono text-xs">{p.similarity_pct}%</span>
                                    {p.appearance_count > 1 && <span className="kai-metadata">×{p.appearance_count}</span>}
                                  </div>
                                  <div className="kai-metadata truncate" style={{ color: BAND_COLOR[p.band] }}>{(BAND_LABEL[p.band] ?? p.band).split(" ")[0]}</div>
                                  {p.name && <div className="truncate text-[11px]">{p.name}</div>}
                                  {p.appearances[0]?.source_url && (
                                    <div className="kai-metadata mt-0.5 flex items-center gap-0.5 truncate">
                                      <ExternalLink size={9} /> source
                                    </div>
                                  )}
                                </div>
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </div>

          {!faces && !detecting && (
            <div className="text-sm text-muted">
              Upload an image — every face is boxed and <span className="text-ink">automatically searched</span> against the index, showing matched images per face.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
