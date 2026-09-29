import type { Point } from "./polygon";

/**
 * Client-side mirror of backend/app/services/layout_validation.py so problems are shown while
 * drawing. The server validates again on save and is authoritative. Coordinates are normalized 0..1.
 */
export const MIN_AREA = 0.0005; // about 0.05 % of the frame
const EPSILON = 1e-12;

export type LayoutIssue = { region_key?: string; region_keys?: string[]; code: string; message: string };
export type PolygonProblem = "TOO_FEW_POINTS" | "OUT_OF_BOUNDS" | "DEGENERATE_POLYGON" | "SELF_INTERSECTING" | null;

export function polygonArea(points: Point[]): number {
  let total = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length];
    total += a.x * b.y - b.x * a.y;
  }
  return Math.abs(total) / 2;
}

const orientation = (a: Point, b: Point, c: Point) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
const onSegment = (a: Point, b: Point, c: Point) => Math.min(a.x, b.x) - EPSILON <= c.x && c.x <= Math.max(a.x, b.x) + EPSILON && Math.min(a.y, b.y) - EPSILON <= c.y && c.y <= Math.max(a.y, b.y) + EPSILON;

export function segmentsIntersect(p1: Point, p2: Point, p3: Point, p4: Point): boolean {
  const d1 = orientation(p3, p4, p1), d2 = orientation(p3, p4, p2), d3 = orientation(p1, p2, p3), d4 = orientation(p1, p2, p4);
  if (((d1 > EPSILON && d2 < -EPSILON) || (d1 < -EPSILON && d2 > EPSILON)) && ((d3 > EPSILON && d4 < -EPSILON) || (d3 < -EPSILON && d4 > EPSILON))) return true;
  return (Math.abs(d1) <= EPSILON && onSegment(p3, p4, p1)) || (Math.abs(d2) <= EPSILON && onSegment(p3, p4, p2)) || (Math.abs(d3) <= EPSILON && onSegment(p1, p2, p3)) || (Math.abs(d4) <= EPSILON && onSegment(p1, p2, p4));
}

export function isSelfIntersecting(points: Point[]): boolean {
  const count = points.length;
  for (let i = 0; i < count; i++) {
    for (let j = i + 1; j < count; j++) {
      if (j === i + 1 || (i === 0 && j === count - 1)) continue; // adjacent edges share a vertex by construction
      if (segmentsIntersect(points[i], points[(i + 1) % count], points[j], points[(j + 1) % count])) return true;
    }
  }
  return false;
}

function pointInPolygon(point: Point, polygon: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if ((a.y > point.y) !== (b.y > point.y) && point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

export function polygonsOverlap(a: Point[], b: Point[]): boolean {
  for (let i = 0; i < a.length; i++) for (let j = 0; j < b.length; j++) if (segmentsIntersect(a[i], a[(i + 1) % a.length], b[j], b[(j + 1) % b.length])) return true;
  return pointInPolygon(a[0], b) || pointInPolygon(b[0], a);
}

export const PROBLEM_MESSAGE: Record<Exclude<PolygonProblem, null>, string> = {
  TOO_FEW_POINTS: "A polygon needs at least three points.",
  OUT_OF_BOUNDS: "Every point must lie inside the frame.",
  DEGENERATE_POLYGON: "The polygon is too small or its points are collinear.",
  SELF_INTERSECTING: "Polygon edges cross each other; reorder or move the points.",
};

/** Same check order as the server: too few, out of bounds, duplicates, self-intersection (before area), then area. */
export function polygonProblem(points: Point[]): PolygonProblem {
  if (points.length < 3) return "TOO_FEW_POINTS";
  if (points.some((p) => p.x < 0 || p.x > 1 || p.y < 0 || p.y > 1)) return "OUT_OF_BOUNDS";
  if (new Set(points.map((p) => `${p.x},${p.y}`)).size < 3) return "DEGENERATE_POLYGON";
  if (isSelfIntersecting(points)) return "SELF_INTERSECTING";
  if (polygonArea(points) < MIN_AREA) return "DEGENERATE_POLYGON";
  return null;
}

export function validateRegions(regions: Array<{ region_key: string; name: string; polygon: Point[] }>): { errors: LayoutIssue[]; warnings: LayoutIssue[] } {
  const errors: LayoutIssue[] = [], warnings: LayoutIssue[] = [];
  const seen = new Set<string>();
  const valid: Array<{ key: string; name: string; polygon: Point[] }> = [];
  for (const region of regions) {
    if (seen.has(region.region_key)) errors.push({ region_key: region.region_key, code: "DUPLICATE_REGION_KEY", message: `“${region.name}” reuses a region key.` });
    seen.add(region.region_key);
    const problem = polygonProblem(region.polygon);
    if (problem) errors.push({ region_key: region.region_key, code: problem, message: `“${region.name}”: ${PROBLEM_MESSAGE[problem]}` });
    else valid.push({ key: region.region_key, name: region.name, polygon: region.polygon });
  }
  for (let i = 0; i < valid.length; i++) {
    for (let j = i + 1; j < valid.length; j++) {
      if (polygonsOverlap(valid[i].polygon, valid[j].polygon)) warnings.push({ region_keys: [valid[i].key, valid[j].key], code: "REGIONS_OVERLAP", message: `“${valid[i].name}” and “${valid[j].name}” overlap; observations inside both may be counted in either.` });
    }
  }
  return { errors, warnings };
}
