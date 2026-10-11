// In-browser face DETECTION (boxes only) via MediaPipe BlazeFace, served fully
// from vendored local assets (no runtime CDN) to keep KAI local-first.
//
// Identity, age/sex and embeddings are NOT done here — those come from the
// backend InsightFace engine via POST /intelligence/face/frame. This detector
// exists only to draw smooth bounding boxes at video framerate, which the
// CPU backend is far too slow to do.
// Type-only import is erased at build time; the heavy runtime module is loaded
// lazily (see getFaceDetector) so it only ships when the Live page is opened.
import type { FaceDetector } from "@mediapipe/tasks-vision";

export interface LiveBox {
  x: number; // pixels in the video's own coordinate space
  y: number;
  w: number;
  h: number;
  score: number;
}

let _detector: FaceDetector | null = null;
let _loading: Promise<FaceDetector> | null = null;

export async function getFaceDetector(): Promise<FaceDetector> {
  if (_detector) return _detector;
  if (_loading) return _loading;
  _loading = (async () => {
    const { FaceDetector, FilesetResolver } = await import("@mediapipe/tasks-vision");
    const fileset = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
    const detector = await FaceDetector.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: "/mediapipe/models/blaze_face_short_range.tflite",
      },
      runningMode: "VIDEO",
      minDetectionConfidence: 0.5,
    });
    _detector = detector;
    return detector;
  })();
  return _loading;
}

/** Run detection on one video frame; returns boxes in video pixel coords. */
export function detectBoxes(
  detector: FaceDetector,
  video: HTMLVideoElement,
  timestampMs: number,
): LiveBox[] {
  const res = detector.detectForVideo(video, timestampMs);
  return (res.detections ?? [])
    .map((d) => {
      const bb = d.boundingBox;
      if (!bb) return null;
      return {
        x: bb.originX,
        y: bb.originY,
        w: bb.width,
        h: bb.height,
        score: d.categories?.[0]?.score ?? 0,
      } as LiveBox;
    })
    .filter((b): b is LiveBox => b !== null);
}

export function disposeFaceDetector(): void {
  try {
    _detector?.close();
  } catch {
    /* ignore */
  }
  _detector = null;
  _loading = null;
}
