"""Geometry validation for classroom region polygons (normalized 0..1 coordinates).

Errors block saving a layout; warnings (overlaps) are reported but allowed
because seats and zones can legitimately overlap. Only the polygons supplied
are analysed - no seats or regions are ever inferred or invented.
"""
from itertools import combinations

MIN_AREA = 0.0005  # ~0.05 % of the frame; smaller is treated as degenerate
EPSILON = 1e-12
Point = tuple[float, float]


def _points(polygon) -> list[Point]:
    return [(float(p["x"]), float(p["y"])) if isinstance(p, dict) else (float(p.x), float(p.y)) for p in polygon]


def polygon_area(points: list[Point]) -> float:
    total = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))
    return abs(total) / 2


def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, c: Point) -> bool:
    return min(a[0], b[0]) - EPSILON <= c[0] <= max(a[0], b[0]) + EPSILON and min(a[1], b[1]) - EPSILON <= c[1] <= max(a[1], b[1]) + EPSILON


def segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    d1, d2, d3, d4 = _orientation(p3, p4, p1), _orientation(p3, p4, p2), _orientation(p1, p2, p3), _orientation(p1, p2, p4)
    if ((d1 > EPSILON and d2 < -EPSILON) or (d1 < -EPSILON and d2 > EPSILON)) and ((d3 > EPSILON and d4 < -EPSILON) or (d3 < -EPSILON and d4 > EPSILON)):
        return True
    return (abs(d1) <= EPSILON and _on_segment(p3, p4, p1)) or (abs(d2) <= EPSILON and _on_segment(p3, p4, p2)) or (abs(d3) <= EPSILON and _on_segment(p1, p2, p3)) or (abs(d4) <= EPSILON and _on_segment(p1, p2, p4))


def is_self_intersecting(points: list[Point]) -> bool:
    count = len(points)
    for i, j in combinations(range(count), 2):
        if j == i + 1 or (i == 0 and j == count - 1):
            continue  # adjacent edges share a vertex by construction
        if segments_intersect(points[i], points[(i + 1) % count], points[j], points[(j + 1) % count]):
            return True
    return False


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def polygons_overlap(a: list[Point], b: list[Point]) -> bool:
    count_a, count_b = len(a), len(b)
    for i in range(count_a):
        for j in range(count_b):
            if segments_intersect(a[i], a[(i + 1) % count_a], b[j], b[(j + 1) % count_b]):
                return True
    return point_in_polygon(a[0], b) or point_in_polygon(b[0], a)


def validate_layout(regions) -> dict:
    errors, warnings, parsed = [], [], {}
    seen_keys: set[str] = set()

    def region_key(region) -> str:
        return region["region_key"] if isinstance(region, dict) else region.region_key

    for region in regions:
        key = region_key(region)
        polygon = region["polygon"] if isinstance(region, dict) else region.polygon
        if key in seen_keys:
            errors.append({"region_key": key, "code": "DUPLICATE_REGION_KEY", "message": f"Region key '{key}' is used more than once."})
        seen_keys.add(key)
        points = _points(polygon)
        if len(points) < 3:
            errors.append({"region_key": key, "code": "TOO_FEW_POINTS", "message": "A polygon needs at least three points."}); continue
        if any(not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0) for x, y in points):
            errors.append({"region_key": key, "code": "OUT_OF_BOUNDS", "message": "Every point must lie inside the frame (0 to 1)."}); continue
        if len(set(points)) < 3:
            errors.append({"region_key": key, "code": "DEGENERATE_POLYGON", "message": "The polygon needs three distinct points."}); continue
        # Self-intersection first: a bow-tie's signed area can cancel to ~0, which would otherwise be mislabelled as degenerate.
        if is_self_intersecting(points):
            errors.append({"region_key": key, "code": "SELF_INTERSECTING", "message": "Polygon edges cross each other; reorder the points."}); continue
        if polygon_area(points) < MIN_AREA:
            errors.append({"region_key": key, "code": "DEGENERATE_POLYGON", "message": "The polygon is too small or its points are collinear."}); continue
        parsed[key] = points
    for first, second in combinations(parsed, 2):
        if polygons_overlap(parsed[first], parsed[second]):
            warnings.append({"region_keys": [first, second], "code": "REGIONS_OVERLAP", "message": f"Regions '{first}' and '{second}' overlap; observations inside both may be counted in either."})
    return {"valid": not errors, "errors": errors, "warnings": warnings}
