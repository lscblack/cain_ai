"""InsightFace (buffalo_l / ArcFace r50) backend — GPU when a real CUDA driver is
present, otherwise CPU with a bounded thread budget so background work (crawling,
discovery, bulk indexing) never saturates the machine."""
from __future__ import annotations

import ctypes
import os
import threading

import numpy as np

from app.core.logging import get_logger
from app.core.config import get_settings
from app.intelligence.face.engine import DetectedFace, FaceEngine

logger = get_logger("kai.face")

_DET_SIZE = (640, 640)


def cuda_is_usable() -> bool:
    """True only if a CUDA driver is actually loadable AND a device exists.

    ``onnxruntime.get_available_providers()`` lists ``CUDAExecutionProvider`` whenever
    the GPU build is installed, even on a box with no NVIDIA driver — so we probe the
    driver directly via libcuda to avoid trying (and failing) to run on a phantom GPU.
    """
    try:
        import onnxruntime as ort

        if "CUDAExecutionProvider" not in ort.get_available_providers():
            return False
    except Exception:
        return False
    for libname in ("libcuda.so.1", "libcuda.so", "nvcuda.dll"):
        try:
            cuda = ctypes.CDLL(libname)
        except OSError:
            continue
        try:
            if cuda.cuInit(0) != 0:  # not CUDA_SUCCESS
                continue
            count = ctypes.c_int(0)
            if cuda.cuDeviceGetCount(ctypes.byref(count)) == 0 and count.value > 0:
                return True
        except Exception:
            continue
    return False


def _cpu_thread_budget() -> int:
    configured = get_settings().face_cpu_threads
    if configured and configured > 0:
        return configured
    cores = os.cpu_count() or 2
    return max(2, cores // 2)


_ort_capped = False


def _cap_onnxruntime_threads(n: int) -> None:
    """Force onnxruntime sessions to a bounded intra-op pool.

    onnxruntime ignores OMP/ORT_NUM_THREADS env vars and sizes its pool to every
    physical core (and pins its own threads), so it hogs the whole machine. There's
    no API hook through insightface, so wrap InferenceSession to inject SessionOptions
    with a capped thread count unless the caller passed their own.
    """
    global _ort_capped
    if _ort_capped:
        return
    try:
        import onnxruntime as ort

        _orig = ort.InferenceSession

        def _capped(*args, **kwargs):
            if not kwargs.get("sess_options"):
                so = ort.SessionOptions()
                so.intra_op_num_threads = max(1, n)
                so.inter_op_num_threads = 1
                kwargs["sess_options"] = so
            return _orig(*args, **kwargs)

        ort.InferenceSession = _capped
        _ort_capped = True
        logger.info("onnxruntime intra-op threads capped at %d", n)
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not cap onnxruntime threads: %s", exc)


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
                use_gpu = get_settings().face_use_gpu and cuda_is_usable()
                if not use_gpu:
                    # Bound CPU thread pools BEFORE importing onnxruntime/insightface so a
                    # single detection can't peg all 24 cores and stall the rest of the box.
                    budget = str(_cpu_thread_budget())
                    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                                "NUMEXPR_NUM_THREADS", "ORT_NUM_THREADS"):
                        os.environ.setdefault(var, budget)
                    _cap_onnxruntime_threads(_cpu_thread_budget())

                from insightface.app import FaceAnalysis

                if use_gpu:
                    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                    ctx_id = 0
                    logger.info("InsightFace GPU acceleration enabled (CUDA device detected)")
                else:
                    providers = ["CPUExecutionProvider"]
                    ctx_id = -1
                    logger.info(
                        "InsightFace running on CPU (no usable CUDA driver); thread budget=%s",
                        os.environ.get("OMP_NUM_THREADS"),
                    )

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
