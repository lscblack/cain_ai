// Client-side face cropping. Keeps crops ephemeral (no backend round-trip just
// to render a thumbnail) and lets us POST a single-face crop when capturing.

export type Bbox = [number, number, number, number]; // [x1, y1, x2, y2]

export interface Crop {
  blob: Blob;
  dataUrl: string;
}

/**
 * Crop the bbox region out of `source`, with a little context padding, into a
 * square-ish JPEG. `source` is anything drawable to a canvas (image, canvas,
 * video frame, bitmap). Coordinates are in the source's own pixel space.
 */
export async function cropFace(
  source: CanvasImageSource,
  bbox: Bbox,
  opts: { pad?: number; maxSize?: number; naturalWidth: number; naturalHeight: number } = {
    naturalWidth: 0,
    naturalHeight: 0,
  },
): Promise<Crop> {
  const pad = opts.pad ?? 0.25;
  const maxSize = opts.maxSize ?? 256;
  const W = opts.naturalWidth;
  const H = opts.naturalHeight;

  const [x1, y1, x2, y2] = bbox;
  const bw = Math.max(1, x2 - x1);
  const bh = Math.max(1, y2 - y1);
  const px = bw * pad;
  const py = bh * pad;

  const sx = Math.max(0, Math.floor(x1 - px));
  const sy = Math.max(0, Math.floor(y1 - py));
  const sw = Math.min(W - sx, Math.ceil(bw + px * 2));
  const sh = Math.min(H - sy, Math.ceil(bh + py * 2));

  const scale = Math.min(1, maxSize / Math.max(sw, sh));
  const dw = Math.max(1, Math.round(sw * scale));
  const dh = Math.max(1, Math.round(sh * scale));

  const canvas = document.createElement("canvas");
  canvas.width = dw;
  canvas.height = dh;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas_2d_unavailable");
  ctx.drawImage(source, sx, sy, sw, sh, 0, 0, dw, dh);

  const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("toBlob_failed"))), "image/jpeg", 0.9),
  );
  return { blob, dataUrl };
}

/** Grab the current video frame as a JPEG blob (for a /frame POST). */
export async function frameToBlob(
  video: HTMLVideoElement,
  maxWidth = 640,
  quality = 0.8,
): Promise<{ blob: Blob; canvas: HTMLCanvasElement; scale: number } | null> {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return null;
  const scale = Math.min(1, maxWidth / vw);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(vw * scale);
  canvas.height = Math.round(vh * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", quality),
  );
  if (!blob) return null;
  return { blob, canvas, scale };
}
