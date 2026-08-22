import math
from dataclasses import dataclass, field

import numpy as np


def eye_aspect_ratio(points: list[tuple[float, float]]) -> float:
    if len(points) != 6:
        raise ValueError("EAR requires exactly six eye landmarks")
    p = np.asarray(points, dtype=float)
    return float((np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])) / max(2 * np.linalg.norm(p[0] - p[3]), 1e-9))


@dataclass
class DrowsinessDetector:
    threshold: float = 0.21
    duration: float = 2.0
    _closed_since: dict[str, float] = field(default_factory=dict)

    def update(self, tracking_id: str, ear: float, timestamp: float) -> dict[str, object]:
        closed = ear < self.threshold
        if closed:
            self._closed_since.setdefault(tracking_id, timestamp)
        else:
            self._closed_since.pop(tracking_id, None)
        elapsed = timestamp - self._closed_since.get(tracking_id, timestamp)
        possible = bool(closed and elapsed >= self.duration)
        confidence = min(1.0, max(0.0, (self.threshold - ear) / max(self.threshold, 1e-9))) if closed else 1.0
        return {"eye_state": "CLOSED" if closed else "OPEN", "possible_drowsiness": possible, "confidence": round(confidence, 2)}
