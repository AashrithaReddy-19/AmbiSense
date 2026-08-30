from dataclasses import dataclass
from uuid import uuid4

from .occupancy import box_iou


@dataclass
class TrackRecord:
    uuid: str; local_id: int; first_seen: float; last_seen: float; observations: int; confidence_sum: float; bbox: list[float]; active: bool = True; expiry_reason: str | None = None

    @property
    def visible_duration(self): return max(0.0, self.last_seen - self.first_seen)
    @property
    def average_confidence(self): return self.confidence_sum / max(1, self.observations)


class TrackLifecycleManager:
    def __init__(self, minimum_observations=3, minimum_duration=1.0, timeout=3.0, reentry_window=8.0, iou_gate=.55):
        self.minimum_observations=minimum_observations; self.minimum_duration=minimum_duration; self.timeout=timeout; self.reentry_window=reentry_window; self.iou_gate=iou_gate; self.tracks: dict[int, TrackRecord]={}

    def observe(self, local_id: int, timestamp: float, confidence: float, bbox: list[float]) -> TrackRecord:
        self.expire(timestamp)
        track=self.tracks.get(local_id)
        if track is None:
            duplicate=next((t for t in self.tracks.values() if not t.active and timestamp-t.last_seen <= self.reentry_window and box_iou(t.bbox,bbox)>=self.iou_gate),None)
            track=duplicate or TrackRecord(str(uuid4()),local_id,timestamp,timestamp,0,0.0,bbox)
            if duplicate: track.local_id=local_id; track.active=True; track.expiry_reason=None
            self.tracks[local_id]=track
        track.last_seen=timestamp; track.observations+=1; track.confidence_sum+=max(0,min(1,float(confidence))); track.bbox=list(bbox); track.active=True
        return track

    def expire(self, timestamp: float):
        for track in self.tracks.values():
            if track.active and timestamp-track.last_seen>self.timeout: track.active=False; track.expiry_reason="TRACK_TIMEOUT"

    def valid_unique_count(self) -> int:
        unique={t.uuid for t in self.tracks.values() if t.observations>=self.minimum_observations and t.visible_duration>=self.minimum_duration and t.average_confidence>=.25}
        return len(unique)
