"""InsightFace (buffalo_l / ArcFace r50) CPU backend."""
from __future__ import annotations

import threading

import numpy as np

from app.core.logging import get_logger
from app.core.config import get_settings
from app.intelligence.face.engine import DetectedFace, FaceEngine

logger = get_logger("kai.face")

_DET_SIZE = (640, 640)


class InsightFaceEngine(FaceEngine):
    model_name = "buffalo_l"
    model_version = "arcface_r50_w600k"
    embedding_dim = 512

    def __init__(self) -> None:
        self._app = None
        self._lock = threading.Lock()
        self._load_error: str | None = None

    def _ensure_loaded(self) -> bool:
        if self._app is not None:
            return True
        if self._load_error is not None:
            return False
        with self._lock:
            if self._app is not None:
                return True
            try:
                from insightface.app import FaceAnalysis

                providers = ["CPUExecutionProvider"]
                ctx_id = -1
                if get_settings().face_use_gpu:
                    try:
                        import onnxruntime as ort

                        if "CUDAExecutionProvider" in ort.get_available_providers():
                            providers.insert(0, "CUDAExecutionProvider")
                            ctx_id = 0
                            logger.info("InsightFace GPU acceleration enabled")
                        else:
                            logger.info("CUDA provider unavailable; using CPU for InsightFace")
                    except Exception as exc:  # GPU support is optional
                        logger.info("GPU setup unavailable; using CPU for InsightFace: %s", exc)

                app = FaceAnalysis(name=self.model_name, providers=providers)
                app.prepare(ctx_id=ctx_id, det_size=_DET_SIZE)
                self._app = app
                logger.info("InsightFace engine loaded (%s) with %s", self.model_name, providers)
                return True
            except Exception as exc:  # model missing / import failure
                self._load_error = str(exc)
                logger.warning("InsightFace engine unavailable: %s", exc)
                return False

    def available(self) -> bool:
        return self._ensure_loaded()

    def _decode(self, image_bytes: bytes):
        import cv2

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img

    @staticmethod
    def _quality(det_score: float, bbox: list[int], img_shape) -> float:
        # Composite: detection confidence weighted with relative face area.
        h, w = img_shape[0], img_shape[1]
        face_w = max(bbox[2] - bbox[0], 1)
        face_h = max(bbox[3] - bbox[1], 1)
        area_ratio = (face_w * face_h) / float(max(w * h, 1))
        size_score = min(area_ratio * 6.0, 1.0)  # ~17% of frame -> full size score
        return float(max(0.0, min(1.0, 0.6 * det_score + 0.4 * size_score)))

    def detect_and_embed(self, image_bytes: bytes) -> list[DetectedFace]:
        if not self._ensure_loaded():
            raise RuntimeError(f"face engine unavailable: {self._load_error}")
        img = self._decode(image_bytes)
        if img is None:
            raise ValueError("could not decode image")
        faces = self._app.get(img)
        out: list[DetectedFace] = []
        for f in faces:
            bbox = [int(v) for v in f.bbox.tolist()]
            emb = [float(x) for x in f.normed_embedding.tolist()]
            out.append(
                DetectedFace(
                    bbox=bbox,
                    det_score=float(f.det_score),
                    embedding=emb,
                    quality=self._quality(float(f.det_score), bbox, img.shape),
                    extra={
                        "age": int(getattr(f, "age", -1)) if getattr(f, "age", None) is not None else None,
                        "sex": getattr(f, "sex", None),
                    },
                )
            )
        # best (highest quality) first
        out.sort(key=lambda d: d.quality, reverse=True)
        return out
