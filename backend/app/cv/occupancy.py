from dataclasses import dataclass

from ..metrics import safe_rate


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
    return {"total_seats": total, "occupied": occupied, "empty": total - occupied, "occupancy_rate": safe_rate(occupied, total), "occupied_seats": occupied_ids}


def box_iou(first: list[float], second: list[float]) -> float:
    x1=max(first[0],second[0]); y1=max(first[1],second[1]); x2=min(first[2],second[2]); y2=min(first[3],second[3])
    intersection=max(0,x2-x1)*max(0,y2-y1)
    area_a=max(0,first[2]-first[0])*max(0,first[3]-first[1]); area_b=max(0,second[2]-second[0])*max(0,second[3]-second[1])
    return intersection/max(area_a+area_b-intersection,1e-9)
