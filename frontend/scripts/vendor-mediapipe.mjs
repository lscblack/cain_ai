// Vendor MediaPipe Tasks-Vision assets into public/mediapipe so the Live Face
// page runs fully local (no runtime CDN) — in keeping with KAI's local-first
// stance. The wasm is copied from the installed npm package (offline); the
// BlazeFace model is downloaded once (network) if missing.
//
// Runs on `pnpm install` (postinstall) and can be re-run manually:
//   node scripts/vendor-mediapipe.mjs
import { cp, mkdir, access, stat } from "node:fs/promises";
import { createWriteStream } from "node:fs";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const WASM_SRC = join(root, "node_modules", "@mediapipe", "tasks-vision", "wasm");
const WASM_DST = join(root, "public", "mediapipe", "wasm");
const MODEL_DST = join(root, "public", "mediapipe", "models", "blaze_face_short_range.tflite");
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite";

async function exists(p) {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

async function copyWasm() {
  if (!(await exists(WASM_SRC))) {
    console.warn("[vendor-mediapipe] wasm source not found (is @mediapipe/tasks-vision installed?) — skipping");
    return;
  }
  await mkdir(WASM_DST, { recursive: true });
  await cp(WASM_SRC, WASM_DST, { recursive: true });
  console.log("[vendor-mediapipe] wasm copied to public/mediapipe/wasm");
}

async function fetchModel() {
  if (await exists(MODEL_DST)) {
    const s = await stat(MODEL_DST);
    if (s.size > 0) return; // already vendored
  }
  await mkdir(dirname(MODEL_DST), { recursive: true });
  try {
    const res = await fetch(MODEL_URL);
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    await pipeline(res.body, createWriteStream(MODEL_DST));
    console.log("[vendor-mediapipe] model downloaded to public/mediapipe/models");
  } catch (e) {
    console.warn(
      `[vendor-mediapipe] could not download the face model (${e}). The Live page will fall ` +
        `back to backend-driven boxes until you run this script again with network access.`,
    );
  }
}

await copyWasm();
await fetchModel();
