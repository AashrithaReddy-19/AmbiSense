from dataclasses import dataclass


@dataclass(frozen=True)
class Seat:
    id: str
    x1: float
    y1: float
    x2: float
    y2: float


def calculate_occupancy(seats: list[Seat], person_centers: list[tuple[float, float]]) -> dict[str, object]:
    occupied_ids = [seat.id for seat in seats if any(seat.x1 <= x <= seat.x2 and seat.y1 <= y <= seat.y2 for x, y in person_centers)]
    occupied = len(occupied_ids)
    total = len(seats)
    return {"total_seats": total, "occupied": occupied, "empty": total - occupied, "occupancy_rate": round(occupied / total * 100, 2) if total else 0.0, "occupied_seats": occupied_ids}
