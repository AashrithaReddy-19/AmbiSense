from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from .drowsiness import eye_aspect_ratio
from .head_pose import HeadPose, estimate_head_pose
from .yawn import mouth_aspect_ratio


LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]
MOUTH = [61, 82, 13, 312, 291, 308, 14, 87]
POSE_POINTS = [1, 152, 33, 263, 61, 291]
MODEL_POINTS = np.array([(0, 0, 0), (0, -63.6, -12.5), (-43.3, 32.7, -26), (43.3, 32.7, -26), (-28.9, -28.9, -24.1), (28.9, -28.9, -24.1)], dtype=np.float64)


@dataclass(frozen=True)
class FaceSignals:
    center: tuple[float, float]
    head_pose: HeadPose
    ear: float
    mar: float


class FaceLandmarkProcessor:
    """MediaPipe Tasks Face Landmarker adapter; it never stores face images."""

    def __init__(self, model_path: Path, max_faces: int = 30):
        if not model_path.exists():
            raise FileNotFoundError(f"Face Landmarker model is missing: {model_path.name}")
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_faces=max_faces,
            min_face_detection_confidence=0.35,
            min_face_presence_confidence=0.35,
            min_tracking_confidence=0.35,
        )
        self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

    def process(self, frame: np.ndarray, timestamp_ms: int) -> list[FaceSignals]:
        height, width = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms)
        return [self._signals(face, width, height) for face in result.face_landmarks]

    def close(self) -> None:
        self.landmarker.close()

    @staticmethod
    def _signals(face, width: int, height: int) -> FaceSignals:
        point = lambda index: (float(face[index].x * width), float(face[index].y * height))
        left_ear = eye_aspect_ratio([point(index) for index in LEFT_EYE])
        right_ear = eye_aspect_ratio([point(index) for index in RIGHT_EYE])
        mar = mouth_aspect_ratio([point(index) for index in MOUTH])
        image_points = np.array([point(index) for index in POSE_POINTS], dtype=np.float64)
        camera = np.array([[width, 0, width / 2], [0, width, height / 2], [0, 0, 1]], dtype=np.float64)
        success, rotation, _translation = cv2.solvePnP(MODEL_POINTS, image_points, camera, np.zeros((4, 1)), flags=cv2.SOLVEPNP_ITERATIVE)
        if success:
            matrix, _ = cv2.Rodrigues(rotation)
            angles, *_ = cv2.RQDecomp3x3(matrix)
            pitch, yaw, roll = (float(value) for value in angles)
            pose = estimate_head_pose(yaw, pitch, roll)
        else:
            pose = HeadPose(0, 0, 0, "UNKNOWN")
        xs = [landmark.x * width for landmark in face]
        ys = [landmark.y * height for landmark in face]
        return FaceSignals(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2), pose, (left_ear + right_ear) / 2, mar)
