"""Generate synthetic classroom sample clips for trying the upload pipeline.

The clips are composed from the two people photos bundled with Ultralytics
(zidane.jpg, bus.jpg). They are not real classroom recordings; they exist so the
real YOLO/ByteTrack/MediaPipe pipeline has people to detect during demos.

Usage: python scripts/generate_sample_videos.py [output_dir]
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import ultralytics

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(ultralytics.__file__).parent / "assets"
FPS = 10
SIZE = (960, 540)


def load(name):
    image = cv2.imread(str(ASSETS / name))
    if image is None:
        raise FileNotFoundError(f"Ultralytics sample image is missing: {name}")
    return image


def crop(image, box):
    x1, y1, x2, y2 = box
    return image[y1:y2, x1:x2]


def classroom_background(width, height, rows):
    """A plain room: wall, board, floor and desk rows."""
    frame = np.full((height, width, 3), (200, 206, 212), dtype=np.uint8)
    cv2.rectangle(frame, (int(width * .2), 18), (int(width * .8), int(height * .16)), (52, 74, 58), -1)
    cv2.rectangle(frame, (0, int(height * .45)), (width, height), (150, 158, 168), -1)
    for row in range(rows):
        y = int(height * (.42 + row * .2)) + 60
        cv2.rectangle(frame, (30, y), (width - 30, y + 14), (90, 110, 140), -1)
    return frame


def paste(frame, person, x, y, height):
    scale = height / person.shape[0]
    resized = cv2.resize(person, (max(1, int(person.shape[1] * scale)), int(height)))
    h, w = resized.shape[:2]
    x, y = int(x), int(y)
    x1, y1, x2, y2 = max(0, x), max(0, y), min(frame.shape[1], x + w), min(frame.shape[0], y + h)
    if x2 > x1 and y2 > y1:
        frame[y1:y2, x1:x2] = resized[y1 - y:y2 - y, x1 - x:x2 - x]


def write(path, frames):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {path}")
    for frame in frames:
        writer.write(cv2.resize(frame, SIZE))
    writer.release()
    return path


def seated_class(people, seats, seconds, arrivals=None, sway=6):
    """Students in desk rows; arrivals maps seat index to the second they appear."""
    arrivals = arrivals or {}
    background = classroom_background(*SIZE, rows=len({row for row, _ in seats}))
    for index in range(seconds * FPS):
        t = index / FPS
        frame = background.copy()
        for seat, (row, column) in enumerate(seats):
            if t < arrivals.get(seat, 0):
                continue
            person = people[seat % len(people)]
            height = 150 + row * 45
            columns = max(c for r, c in seats if r == row) + 1
            x = 40 + column * (SIZE[0] - 80) / columns + sway * math.sin(t * 1.3 + seat)
            y = SIZE[1] * (.18 + row * .2)
            paste(frame, person, x, y, height)
        yield frame


def pan_zoom(image, seconds, zoom_from, zoom_to, center_from, center_to):
    h, w = image.shape[:2]
    for index in range(seconds * FPS):
        p = index / max(1, seconds * FPS - 1)
        zoom = zoom_from + (zoom_to - zoom_from) * p
        cx = (center_from[0] + (center_to[0] - center_from[0]) * p) * w
        cy = (center_from[1] + (center_to[1] - center_from[1]) * p) * h
        cw, ch = w / zoom, w / zoom * SIZE[1] / SIZE[0]
        x1 = int(min(max(0, cx - cw / 2), w - cw)); y1 = int(min(max(0, cy - ch / 2), h - ch))
        yield image[y1:y1 + int(ch), x1:x1 + int(cw)]


def main(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    zidane, bus = load("zidane.jpg"), load("bus.jpg")
    people = [
        crop(zidane, (60, 40, 560, 720)), crop(zidane, (700, 0, 1180, 720)),
        crop(bus, (40, 220, 260, 900)), crop(bus, (210, 230, 380, 860)),
        crop(bus, (650, 220, 810, 880)), crop(bus, (0, 540, 90, 880)),
    ]
    clips = {
        "01_lecture_full_room.mp4": seated_class(people, [(0, c) for c in range(5)] + [(1, c) for c in range(4)], 24),
        "02_lecture_late_arrivals.mp4": seated_class(people, [(0, c) for c in range(4)] + [(1, c) for c in range(3)], 30, arrivals={1: 6, 3: 12, 4: 18, 6: 24}),
        "03_small_group_discussion.mp4": seated_class(people[:4], [(0, c) for c in range(2)] + [(1, c) for c in range(2)], 20, sway=18),
        "04_seminar_closeup.mp4": pan_zoom(zidane, 20, 1.1, 1.8, (.5, .45), (.75, .4)),
        "05_two_students_wide.mp4": pan_zoom(zidane, 16, 1.0, 1.25, (.5, .5), (.45, .5)),
        "06_corridor_group.mp4": pan_zoom(bus, 16, 1.0, 1.3, (.5, .55), (.45, .6)),
    }
    for name, frames in clips.items():
        path = write(output / name, frames)
        print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}  {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "sample_videos")
