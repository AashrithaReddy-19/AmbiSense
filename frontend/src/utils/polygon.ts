export type Point = { x: number; y: number };
export const clamp = (value: number) => Math.max(0, Math.min(1, value));
export function normalizePoint(
  x: number,
  y: number,
  width: number,
  height: number,
): Point {
  return {
    x: Number(clamp(x / Math.max(width, 1)).toFixed(4)),
    y: Number(clamp(y / Math.max(height, 1)).toFixed(4)),
  };
}
export function polygonValid(points: Point[]): boolean {
  if (points.length < 3) return false;
  let area = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[i],
      b = points[(i + 1) % points.length];
    area += a.x * b.y - b.x * a.y;
  }
  return Math.abs(area / 2) > 0.0001;
}
export function updateVertex(
  points: Point[],
  index: number,
  next: Point,
): Point[] {
  return points.map((point, i) =>
    i === index ? { x: clamp(next.x), y: clamp(next.y) } : point,
  );
}
export function removeVertex(points: Point[], index: number): Point[] {
  if (points.length <= 3) return points;
  const next = points.filter((_, i) => i !== index);
  return polygonValid(next) ? next : points;
}
export function movePolygon(points: Point[], dx: number, dy: number): Point[] {
  const minX = Math.min(...points.map((p) => p.x)),
    maxX = Math.max(...points.map((p) => p.x)),
    minY = Math.min(...points.map((p) => p.y)),
    maxY = Math.max(...points.map((p) => p.y));
  const safeX = Math.max(-minX, Math.min(1 - maxX, dx)),
    safeY = Math.max(-minY, Math.min(1 - maxY, dy));
  return points.map((p) => ({
    x: Number((p.x + safeX).toFixed(4)),
    y: Number((p.y + safeY).toFixed(4)),
  }));
}
