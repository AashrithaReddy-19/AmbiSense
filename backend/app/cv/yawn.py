from dataclasses import dataclass, field

import numpy as np


def mouth_aspect_ratio(points: list[tuple[float, float]]) -> float:
    if len(points) != 8:
        raise ValueError("MAR requires exactly eight mouth landmarks")
    p = np.asarray(points, dtype=float)
    vertical = np.linalg.norm(p[1] - p[7]) + np.linalg.norm(p[2] - p[6]) + np.linalg.norm(p[3] - p[5])
    return float(vertical / max(3 * np.linalg.norm(p[0] - p[4]), 1e-9))


@dataclass
class YawnDetector:
    threshold: float = 0.6
    minimum_duration: float = 1.0
    _open_since: dict[str, float] = field(default_factory=dict)
    _active: set[str] = field(default_factory=set)
    counts: dict[str, int] = field(default_factory=dict)

    def update(self, tracking_id: str, mar: float, timestamp: float) -> dict[str, object]:
        if mar > self.threshold:
            self._open_since.setdefault(tracking_id, timestamp)
        else:
            self._open_since.pop(tracking_id, None)
            self._active.discard(tracking_id)
        yawning = mar > self.threshold and timestamp - self._open_since.get(tracking_id, timestamp) >= self.minimum_duration
        if yawning and tracking_id not in self._active:
            self.counts[tracking_id] = self.counts.get(tracking_id, 0) + 1
            self._active.add(tracking_id)
        return {"yawning": yawning, "yawn_count": self.counts.get(tracking_id, 0), "mar": round(mar, 3)}
