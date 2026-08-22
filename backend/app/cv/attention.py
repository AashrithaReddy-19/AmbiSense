from dataclasses import dataclass, field


@dataclass
class AttentionEstimator:
    alpha: float = 0.4
    _scores: dict[str, float] = field(default_factory=dict)

    def estimate(self, tracking_id: str, direction: str) -> dict[str, float | str]:
        states = {
            "FRONT": ("ATTENTIVE", 1.0), "DOWN": ("LOOKING_DOWN", 0.25),
            "LEFT": ("LOOKING_LEFT", 0.4), "RIGHT": ("LOOKING_RIGHT", 0.4),
            "UP": ("LOOKING_AWAY", 0.2),
        }
        state, current = states.get(direction, ("UNKNOWN", 0.0))
        previous = self._scores.get(tracking_id, current)
        smoothed = self.alpha * current + (1 - self.alpha) * previous
        self._scores[tracking_id] = smoothed
        return {"state": state, "score": round(smoothed * 100, 2), "metric": "visual attention estimate"}
