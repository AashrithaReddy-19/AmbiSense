from dataclasses import dataclass


@dataclass(frozen=True)
class HeadPose:
    yaw: float
    pitch: float
    roll: float
    direction: str


def estimate_head_pose(yaw: float, pitch: float, roll: float, threshold: float = 18.0) -> HeadPose:
    """Classify angles produced by a landmark/PnP implementation."""
    if pitch > threshold:
        direction = "DOWN"
    elif pitch < -threshold:
        direction = "UP"
    elif yaw > threshold:
        direction = "RIGHT"
    elif yaw < -threshold:
        direction = "LEFT"
    else:
        direction = "FRONT"
    return HeadPose(round(yaw, 2), round(pitch, 2), round(roll, 2), direction)
