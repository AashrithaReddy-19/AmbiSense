import pytest

from backend.app.cv.drowsiness import DrowsinessDetector, eye_aspect_ratio
from backend.app.cv.engagement import calculate_engagement, calculate_fatigue
from backend.app.cv.head_pose import estimate_head_pose
from backend.app.cv.occupancy import Seat, calculate_occupancy
from backend.app.cv.yawn import YawnDetector, mouth_aspect_ratio


def test_head_pose_directions():
    assert estimate_head_pose(0, 0, 0).direction == "FRONT"
    assert estimate_head_pose(-25, 0, 0).direction == "LEFT"
    assert estimate_head_pose(0, 25, 0).direction == "DOWN"


def test_ear_and_temporal_drowsiness():
    assert eye_aspect_ratio([(0, 0), (1, 1), (2, 1), (3, 0), (2, -1), (1, -1)]) == pytest.approx(2 / 3)
    detector = DrowsinessDetector(threshold=0.21, duration=2)
    assert not detector.update("Student_01", 0.1, 0)["possible_drowsiness"]
    assert detector.update("Student_01", 0.1, 2.1)["possible_drowsiness"]


def test_mar_and_temporal_yawn():
    value = mouth_aspect_ratio([(0, 0), (1, 2), (2, 2), (3, 2), (4, 0), (3, -2), (2, -2), (1, -2)])
    detector = YawnDetector(threshold=0.6, minimum_duration=1)
    detector.update("Student_01", value, 0)
    assert detector.update("Student_01", value, 1.1)["yawning"]


def test_engagement_and_fatigue_bounds():
    assert calculate_engagement({"attention": 100, "orientation": 100, "eye_state": 100, "activity": 100, "expression": 100})["engagement_score"] == 100
    assert calculate_fatigue(200, 200, 200, 200)["fatigue_score"] == 100


def test_occupancy_and_attendance_math():
    result = calculate_occupancy([Seat("Seat 01", 0, 0, 10, 10), Seat("Seat 02", 11, 0, 20, 10)], [(5, 5)])
    assert result["occupied"] == 1
    assert result["occupancy_rate"] == 50
