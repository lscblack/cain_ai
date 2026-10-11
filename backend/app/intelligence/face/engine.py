"""Face engine abstraction.

The investigation layer depends only on this interface, so the ArcFace backend
can be swapped (GPU, a different model, a remote service) without changes. If no
engine is available the app still runs and face endpoints report UNAVAILABLE.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DetectedFace:
    bbox: list[int]  # [x1, y1, x2, y2]
    det_score: float
    embedding: list[float]
    quality: float  # 0..1 composite of detection score and face size
    extra: dict = field(default_factory=dict)

    def to_dict(self, *, include_embedding: bool = False, include_extra: bool = False) -> dict:
        d = {
            "bbox": self.bbox,
            "det_score": round(self.det_score, 4),
            "quality": round(self.quality, 4),
            "embedding_dim": len(self.embedding),
        }
        if include_extra:
            # Only the known demographic attributes from the genderage model.
            d["age"] = (self.extra or {}).get("age")
            d["sex"] = (self.extra or {}).get("sex")
        if include_embedding:
            d["embedding"] = self.embedding
        return d


class FaceEngine:
    """Interface for a face detector + embedder."""

    model_name: str = "unknown"
    model_version: str = "0"
    embedding_dim: int = 0

    def available(self) -> bool:
        raise NotImplementedError

    def detect_and_embed(self, image_bytes: bytes) -> list[DetectedFace]:
        raise NotImplementedError
