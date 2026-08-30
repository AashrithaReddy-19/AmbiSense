import { describe, expect, it } from "vitest";
import {
  movePolygon,
  normalizePoint,
  polygonValid,
  removeVertex,
  updateVertex,
} from "./polygon";
describe("normalized polygon editing", () => {
  const square = [
    { x: 0.1, y: 0.1 },
    { x: 0.5, y: 0.1 },
    { x: 0.5, y: 0.5 },
    { x: 0.1, y: 0.5 },
  ];
  it("normalizes and clamps canvas coordinates", () => {
    expect(normalizePoint(500, 300, 1000, 600)).toEqual({ x: 0.5, y: 0.5 });
    expect(normalizePoint(1200, -5, 1000, 600)).toEqual({ x: 1, y: 0 });
  });
  it("drags vertices without leaving normalized bounds", () => {
    expect(updateVertex(square, 0, { x: -1, y: 2 })[0]).toEqual({ x: 0, y: 1 });
  });
  it("moves a region without crossing canvas edges", () => {
    const moved = movePolygon(square, 1, 1);
    expect(Math.max(...moved.map((p) => p.x))).toBe(1);
    expect(Math.max(...moved.map((p) => p.y))).toBe(1);
  });
  it("prevents invalid polygon removal", () => {
    const triangle = square.slice(0, 3);
    expect(removeVertex(triangle, 0)).toEqual(triangle);
    expect(removeVertex(square, 0)).toHaveLength(3);
  });
  it("rejects collinear polygons", () => {
    expect(
      polygonValid([
        { x: 0, y: 0 },
        { x: 0.5, y: 0.5 },
        { x: 1, y: 1 },
      ]),
    ).toBe(false);
    expect(polygonValid(square)).toBe(true);
  });
});
