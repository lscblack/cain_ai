import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, CameraOff, FolderPlus, Video } from "lucide-react";

import { api } from "@/lib/api";
import { cropFace, frameToBlob, type Bbox } from "@/lib/faceCrop";
import { getFaceDetector, detectBoxes, disposeFaceDetector, type LiveBox } from "@/lib/faceDetector";
import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

const POST_INTERVAL_MS = 1500; // how often a frame is sent to the backend engine

interface FrameMatch {
  face_id: string;
  similarity_pct: number;
  band: string;
  names?: string[];
  page_title?: string | null;
  source_url?: string | null;
}
interface FrameFace {
  bbox: Bbox;
  quality: number;
  det_score: number;
  age: number | null;
  sex: string | null;
  match: FrameMatch | null;
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

export function FaceLive() {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detectorMode, setDetectorMode] = useState<"loading" | "browser" | "backend">("loading");
  const [faces, setFaces] = useState<FrameFace[]>([]);
  const [thumbs, setThumbs] = useState<string[]>([]);
  const [indexedCount, setIndexedCount] = useState<number | null>(null);
  const [faceCount, setFaceCount] = useState(0);
  const [doMatch, setDoMatch] = useState(true);
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [caseId, setCaseId] = useState("");
  const [captured, setCaptured] = useState<string | null>(null);
  const [engineOnline, setEngineOnline] = useState<boolean | null>(null);
  // Diagnostics for the backend enrichment boundary (POST /frame).
  const [diag, setDiag] = useState<{
    analyzing: boolean;
    lastCount: number | null;
    lastMs: number | null;
    lastError: string | null;
  }>({ analyzing: false, lastCount: null, lastMs: null, lastError: null });

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastPostRef = useRef(0);
  const inFlightRef = useRef(false);
  // Last frame sent to the backend, kept only in memory for cropping thumbnails
  // and captures. Never written to disk — the live feed is ephemeral.
  const lastFrameRef = useRef<{ canvas: HTMLCanvasElement; scale: number } | null>(null);
  const facesRef = useRef<FrameFace[]>([]);
  const runningRef = useRef(false);

  useEffect(() => {
    investigationsApi.list().then(setCases).catch(() => setCases([]));
    api
      .get<{ available: boolean }>("/intelligence/face/status")
      .then((s) => setEngineOnline(s.available))
      .catch(() => setEngineOnline(false));
  }, []);

  const postFrame = useCallback(
    async (video: HTMLVideoElement) => {
      inFlightRef.current = true;
      setDiag((d) => ({ ...d, analyzing: true }));
      const t0 = performance.now();
      try {
        const grab = await frameToBlob(video, 640, 0.8);
        if (!grab) {
          setDiag((d) => ({ ...d, analyzing: false, lastError: "could not capture video frame" }));
          return;
        }
        lastFrameRef.current = { canvas: grab.canvas, scale: grab.scale };
        const fd = new FormData();
        fd.append("file", new File([grab.blob], "frame.jpg", { type: "image/jpeg" }));
        fd.append("match", String(doMatch));
        if (caseId) fd.append("investigation_id", caseId);
        const r = await api.postForm<{
          faces: FrameFace[];
          faces_detected: number;
          indexed_faces: number;
        }>("/intelligence/face/frame", fd);
        const faces = r.faces ?? [];
        facesRef.current = faces;
        setFaces(faces);
        setFaceCount(r.faces_detected ?? 0);
        setIndexedCount(r.indexed_faces ?? 0);
        // Padded crops so the thumbnail shows the whole head, not InsightFace's
        // tight landmark box.
        const cv = lastFrameRef.current?.canvas;
        if (cv) {
          const made = await Promise.all(
            faces.map(async (f) => {
              try {
                const c = await cropFace(cv, f.bbox, {
                  pad: 0.45,
                  maxSize: 160,
                  naturalWidth: cv.width,
                  naturalHeight: cv.height,
                });
                return c.dataUrl;
              } catch {
                return "";
              }
            }),
          );
          setThumbs(made);
        }
        setDiag({
          analyzing: false,
          lastCount: r.faces_detected ?? 0,
          lastMs: Math.round(performance.now() - t0),
          lastError: null,
        });
      } catch (e: any) {
        setDiag((d) => ({
          ...d,
          analyzing: false,
          lastMs: Math.round(performance.now() - t0),
          lastError: e?.detail ? String(e.detail) : e?.message ? String(e.message) : "frame request failed",
        }));
      } finally {
        inFlightRef.current = false;
      }
    },
    [doMatch, caseId],
  );

  const loop = useCallback(async () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!runningRef.current || !video || !canvas) return;

    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (vw && vh) {
      if (canvas.width !== vw) canvas.width = vw;
      if (canvas.height !== vh) canvas.height = vh;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.clearRect(0, 0, vw, vh);

        // Prefer smooth in-browser boxes; fall back to backend bboxes.
        let boxes: LiveBox[] = [];
        if (detectorMode === "browser") {
          try {
            const det = await getFaceDetector();
            boxes = detectBoxes(det, video, performance.now());
          } catch {
            /* ignore a single bad frame */
          }
        }
        if (boxes.length === 0 && facesRef.current.length) {
          const s = lastFrameRef.current?.scale ?? 1;
          boxes = facesRef.current.map((f) => ({
            x: f.bbox[0] / s,
            y: f.bbox[1] / s,
            w: (f.bbox[2] - f.bbox[0]) / s,
            h: (f.bbox[3] - f.bbox[1]) / s,
            score: f.det_score,
          }));
        }

        const s = lastFrameRef.current?.scale ?? 1;
        for (const b of boxes) {
          // Attach the nearest backend match (if any) for a live on-box label.
          const cx = b.x + b.w / 2;
          const cy = b.y + b.h / 2;
          let near: FrameFace | null = null;
          let best = Infinity;
          for (const f of facesRef.current) {
            const fx = (f.bbox[0] + f.bbox[2]) / 2 / s;
            const fy = (f.bbox[1] + f.bbox[3]) / 2 / s;
            const d = (fx - cx) ** 2 + (fy - cy) ** 2;
            if (d < best) {
              best = d;
              near = f;
            }
          }
          const withinFace = best <= (b.w * 0.6) ** 2;
          const band = withinFace && near?.match ? near.match.band : null;
          const color = band ? BAND_COLOR[band] : "#4ea1ff";
          ctx.strokeStyle = color;
          ctx.lineWidth = Math.max(2, vw / 300);
          ctx.strokeRect(b.x, b.y, b.w, b.h);
          if (withinFace && near) {
            const label =
              (near.match ? `${near.match.similarity_pct}% ` : "") +
              [near.sex, (near.age ?? 0) > 0 ? `${near.age}y` : null].filter(Boolean).join(" ");
            if (label.trim()) {
              ctx.font = `${Math.max(14, vw / 45)}px monospace`;
              const tw = ctx.measureText(label).width;
              ctx.fillStyle = color;
              ctx.fillRect(b.x, Math.max(0, b.y - 22), tw + 10, 20);
              ctx.fillStyle = "#000";
              ctx.fillText(label, b.x + 5, Math.max(14, b.y - 7));
            }
          }
        }
      }
    }

    // Throttled backend enrichment.
    const now = performance.now();
    if (engineOnline && !inFlightRef.current && now - lastPostRef.current > POST_INTERVAL_MS) {
      lastPostRef.current = now;
      void postFrame(video);
    }

    rafRef.current = requestAnimationFrame(() => void loop());
  }, [detectorMode, engineOnline, postFrame]);

  const stop = useCallback(() => {
    runningRef.current = false;
    setRunning(false);
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    lastFrameRef.current = null;
    facesRef.current = [];
    setFaces([]);
    setThumbs([]);
    setFaceCount(0);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setCaptured(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 } },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (!video) return;
      video.srcObject = stream;
      await video.play();
      runningRef.current = true;
      setRunning(true);

      // Warm up the in-browser detector; fall back to backend boxes if it fails.
      setDetectorMode("loading");
      try {
        await getFaceDetector();
        setDetectorMode("browser");
      } catch {
        setDetectorMode("backend");
      }
      rafRef.current = requestAnimationFrame(() => void loop());
    } catch (e: any) {
      if (e?.name === "NotAllowedError") setError("Camera permission denied.");
      else if (e?.name === "NotFoundError") setError("No camera found on this device.");
      else setError("Could not start the camera.");
    }
  }, [loop]);

  // Restart the rAF loop when its dependencies change mid-session.
  useEffect(() => {
    if (!runningRef.current) return;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => void loop());
  }, [loop]);

  useEffect(() => {
    return () => {
      runningRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      disposeFaceDetector();
    };
  }, []);

  async function captureFace(face: FrameFace) {
    const frame = lastFrameRef.current;
    if (!caseId || !frame) return;
    try {
      const c = await cropFace(frame.canvas, face.bbox, {
        pad: 0.5,
        naturalWidth: frame.canvas.width,
        naturalHeight: frame.canvas.height,
        maxSize: 512,
      });
      const fd = new FormData();
      fd.append("file", new File([c.blob], "live.jpg", { type: "image/jpeg" }));
      fd.append("investigation_id", caseId);
      fd.append("source_url", `webcam:${new Date().toISOString()}`);
      await api.postForm("/intelligence/face/detect", fd);
      const name = cases.find((x) => x.id === caseId)?.name ?? "case";
      setCaptured(`Saved a face to ${name}`);
    } catch {
      setCaptured("Capture failed.");
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <Video size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Live Face Detection</h1>
        <span className="ml-auto kai-metadata">
          {engineOnline === false ? (
            <span style={{ color: "var(--kai-accent)" }}>ENGINE OFFLINE — boxes only</span>
          ) : running ? (
            <>
              <span style={{ color: "var(--kai-verified)" }}>● LIVE</span> · {faceCount} face
              {faceCount === 1 ? "" : "s"} ·{" "}
              {detectorMode === "browser"
                ? "in-browser boxes"
                : detectorMode === "backend"
                  ? "backend boxes"
                  : "loading…"}
            </>
          ) : (
            "camera stopped"
          )}
        </span>
      </div>

      <div
        className="mb-4 rounded-md border px-3 py-2 kai-metadata"
        style={{ borderColor: "var(--kai-border)", color: "var(--kai-muted)" }}
      >
        Live video is processed in memory and never recorded. Matches are potential leads to observe,
        never confirmed identity. Use only on footage you are authorized to analyze.
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <div className="space-y-3">
          <div
            className="relative overflow-hidden rounded-lg border border-line bg-black"
            style={{ aspectRatio: "4 / 3" }}
          >
            <video ref={videoRef} playsInline muted className="h-full w-full object-contain" />
            <canvas
              ref={canvasRef}
              className="pointer-events-none absolute inset-0 h-full w-full object-contain"
            />
            {!running && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-muted">
                <Camera size={32} />
                <span className="text-sm">Camera is off</span>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {!running ? (
              <button
                onClick={start}
                className="flex items-center gap-2 rounded-md border border-line bg-panel px-3 py-2 text-sm hover:bg-panel-2"
              >
                <Camera size={15} /> Start camera
              </button>
            ) : (
              <button
                onClick={stop}
                className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-panel-2"
                style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}
              >
                <CameraOff size={15} /> Stop
              </button>
            )}
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={doMatch} onChange={(e) => setDoMatch(e.target.checked)} />
              Match against local index
            </label>
            {running && (
              <button
                onClick={() => {
                  const v = videoRef.current;
                  if (v && !inFlightRef.current) {
                    lastPostRef.current = performance.now();
                    void postFrame(v);
                  }
                }}
                className="rounded-md border border-line bg-panel px-3 py-2 text-sm hover:bg-panel-2"
              >
                Analyze now
              </button>
            )}
            {error && (
              <span className="text-xs" style={{ color: "var(--kai-accent)" }}>
                {error}
              </span>
            )}
          </div>

          {/* Diagnostics for the detect → embed → match pipeline */}
          <div
            className="rounded-md border px-3 py-2 font-mono text-[11px] leading-relaxed"
            style={{ borderColor: "var(--kai-border)", color: "var(--kai-muted)" }}
          >
            <div>
              engine:{" "}
              <span style={{ color: engineOnline ? "var(--kai-verified)" : "var(--kai-accent)" }}>
                {engineOnline === null ? "checking…" : engineOnline ? "online" : "OFFLINE"}
              </span>
              {"  ·  "}in-browser detector:{" "}
              <span style={{ color: detectorMode === "browser" ? "var(--kai-verified)" : "var(--kai-warn)" }}>
                {detectorMode}
              </span>
            </div>
            <div>
              last /frame:{" "}
              {diag.analyzing
                ? "analyzing…"
                : diag.lastCount === null
                  ? "— (not run yet)"
                  : `${diag.lastCount} face(s) in ${diag.lastMs}ms`}
            </div>
            {diag.lastError && (
              <div style={{ color: "var(--kai-accent)" }}>error: {diag.lastError}</div>
            )}
            {!engineOnline && engineOnline !== null && (
              <div style={{ color: "var(--kai-accent)" }}>
                Backend face engine is offline — age/sex/identity are disabled; only boxes are drawn.
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <span className="kai-metadata uppercase">Capture to case</span>
            <select
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              className="rounded-md border border-line bg-panel px-2 py-1.5 text-sm"
            >
              <option value="">— none —</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {captured && (
              <span className="kai-metadata" style={{ color: "var(--kai-verified)" }}>
                ✓ {captured}
              </span>
            )}
          </div>
        </div>

        {/* Live per-face results */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="kai-metadata uppercase">Faces in view</span>
            {doMatch && indexedCount !== null && (
              <span className="kai-metadata" title="Every detected face is compared against the local face index each scan">
                {diag.analyzing ? "scanning…" : `scanning ${indexedCount} indexed`}
              </span>
            )}
          </div>
          {faces.length === 0 ? (
            <div className="text-sm text-muted">
              {running ? "No face detected yet." : "Start the camera to detect faces live."}
            </div>
          ) : (
            <div className="space-y-2">
              {faces.map((f, i) => {
                const thumb = thumbs[i] || null;
                return (
                  <div key={i} className="flex gap-3 rounded-lg border border-line bg-panel p-2">
                    <div className="h-24 w-24 shrink-0 overflow-hidden rounded border border-line">
                      {thumb ? (
                        <img src={thumb} alt={`face ${i + 1}`} className="h-full w-full object-cover" />
                      ) : (
                        <div className="h-full w-full bg-panel-2" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm">
                        {[f.sex, (f.age ?? 0) > 0 ? `~${f.age}y` : null].filter(Boolean).join(" · ") ||
                          "age/sex n/a"}
                      </div>
                      <div className="kai-metadata">q {Math.round(f.quality * 100)}%</div>
                      {f.match ? (
                        <div className="mt-1">
                          <span className="font-mono text-sm">{f.match.similarity_pct}%</span>{" "}
                          <span className="kai-metadata" style={{ color: BAND_COLOR[f.match.band] }}>
                            {BAND_LABEL[f.match.band] ?? f.match.band}
                          </span>
                          {(f.match.names?.[0] || f.match.page_title) && (
                            <div className="truncate text-xs">
                              {f.match.names?.[0] ?? f.match.page_title}
                            </div>
                          )}
                        </div>
                      ) : (
                        doMatch && (
                          <div className="kai-metadata mt-1">
                            no match among {indexedCount ?? 0} indexed face
                            {indexedCount === 1 ? "" : "s"}
                          </div>
                        )
                      )}
                      <button
                        onClick={() => captureFace(f)}
                        disabled={!caseId}
                        title={!caseId ? "Select an investigation first" : "Store this face"}
                        className="mt-1 flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs hover:bg-panel-2 disabled:opacity-50"
                      >
                        <FolderPlus size={12} /> Capture
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
