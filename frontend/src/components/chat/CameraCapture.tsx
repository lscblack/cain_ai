import { useEffect, useRef, useState } from "react";
import { Camera, X, RefreshCw } from "lucide-react";

/** Live-camera modal: opens the webcam, captures a still frame, and hands it
 * back as a File so the chat can run a face search on it. */
export function CameraCapture({ onCapture, onClose }: {
  onCapture: (file: File) => void;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    if (!navigator.mediaDevices?.getUserMedia) {
      setErr("This browser has no camera access.");
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false })
      .then((stream) => {
        if (!active) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => { /* */ });
          setReady(true);
        }
      })
      .catch((e) => setErr(e?.name === "NotAllowedError" ? "Camera permission denied." : "Could not open the camera."));
    return () => {
      active = false;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  function capture() {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(v, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const file = new File([blob], `camera-${Date.now()}.jpg`, { type: "image/jpeg" });
      streamRef.current?.getTracks().forEach((t) => t.stop());
      onCapture(file);
      onClose();
    }, "image/jpeg", 0.92);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="flex w-full max-w-lg flex-col rounded-lg border border-line bg-panel shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <Camera size={16} style={{ color: "var(--kai-hud)" }} />
            <span className="hud-mono text-sm" style={{ color: "var(--kai-hud)" }}>Live camera</span>
          </div>
          <button onClick={onClose} className="text-muted hover:text-ink"><X size={16} /></button>
        </div>
        <div className="p-4">
          {err ? (
            <div className="flex flex-col items-center gap-3 py-8 text-sm text-muted">
              <Camera size={28} className="text-muted" />
              <div style={{ color: "var(--kai-accent)" }}>{err}</div>
            </div>
          ) : (
            <div className="relative overflow-hidden rounded border border-line" style={{ background: "#000" }}>
              <video ref={videoRef} playsInline muted className="h-auto w-full" style={{ maxHeight: "60vh" }} />
              {!ready && <div className="absolute inset-0 flex items-center justify-center kai-metadata">starting camera…</div>}
              {/* HUD reticle */}
              <div className="pointer-events-none absolute inset-0 hud-frame" />
            </div>
          )}
        </div>
        <div className="flex items-center justify-center gap-2 border-t border-line px-4 py-3">
          <button onClick={capture} disabled={!ready || !!err}
            className="flex items-center gap-2 rounded border px-4 py-2 text-sm hover:bg-panel-2 disabled:opacity-40"
            style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" }}>
            <Camera size={15} /> Capture & search
          </button>
          <button onClick={onClose} className="flex items-center gap-1 rounded border border-line px-3 py-2 text-sm hover:bg-panel">
            <RefreshCw size={13} /> Cancel
          </button>
        </div>
        <div className="kai-metadata px-4 pb-3 text-center">Captures one frame and runs a face search (DB/Web per your toggle).</div>
      </div>
    </div>
  );
}
