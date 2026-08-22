from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


@dataclass(frozen=True)
class PoseSignals:
    center: tuple[float, float]
    raised_hand: bool
    confidence: float


class PoseProcessor:
    """MediaPipe multi-pose adapter for anonymous raised-hand estimation."""

    def __init__(self, model_path: Path, max_poses: int = 30):
        if not model_path.exists():
            raise FileNotFoundError(f"Pose Landmarker model is missing: {model_path.name}")
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=max_poses,
            min_pose_detection_confidence=.35,
            min_pose_presence_confidence=.35,
            min_tracking_confidence=.35,
        )
        self.landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)

    def process(self, frame: np.ndarray, timestamp_ms: int) -> list[PoseSignals]:
        height, width = frame.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        result = self.landmarker.detect_for_video(image, timestamp_ms)
        signals = []
        for pose in result.pose_landmarks:
            left_shoulder, right_shoulder = pose[11], pose[12]
            left_wrist, right_wrist = pose[15], pose[16]
            raised = (float(left_wrist.visibility or 0) > .4 and left_wrist.y < left_shoulder.y) or (float(right_wrist.visibility or 0) > .4 and right_wrist.y < right_shoulder.y)
            confidence = max(float(left_wrist.visibility or 0), float(right_wrist.visibility or 0))
            signals.append(PoseSignals((((left_shoulder.x + right_shoulder.x) / 2) * width, ((left_shoulder.y + right_shoulder.y) / 2) * height), raised, confidence))
        return signals

    def close(self) -> None:
        self.landmarker.close()
