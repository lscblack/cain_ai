"""Face-crop thumbnails: cropped face regions saved for the UI scanner + results."""
from __future__ import annotations

import io
from pathlib import Path

CROPS_DIR = Path(__file__).resolve().parents[4] / "data" / "face_crops"


def crop_path(face_id: str) -> Path:
    return CROPS_DIR / f"{face_id}.jpg"


def save_crop(image_bytes: bytes, bbox: list[int], face_id: str, *, pad: float = 0.25) -> bool:
    """Crop the face region (with padding) and save a small JPEG. Best-effort."""
    try:
        from PIL import Image as PILImage

        CROPS_DIR.mkdir(parents=True, exist_ok=True)
        img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        x1, y1, x2, y2 = bbox
        bw, bh = max(x2 - x1, 1), max(y2 - y1, 1)
        px, py = int(bw * pad), int(bh * pad)
        box = (max(0, x1 - px), max(0, y1 - py), min(w, x2 + px), min(h, y2 + py))
        crop = img.crop(box)
        crop.thumbnail((256, 256))
        crop.save(crop_path(face_id), format="JPEG", quality=82)
        return True
    except Exception:
        return False


def has_crop(face_id: str) -> bool:
    return crop_path(face_id).exists()
