import { describe, expect, it } from "vitest";
import { isSelfIntersecting, polygonArea, polygonProblem, polygonsOverlap, segmentsIntersect, validateRegions } from "./layoutValidation";

const square = (x: number, y: number, size = 0.2) => [{ x, y }, { x: x + size, y }, { x: x + size, y: y + size }, { x, y: y + size }];
const region = (key: string, polygon: Array<{ x: number; y: number }>) => ({ region_key: key, name: key.toUpperCase(), polygon });

describe("geometry", () => {
  it("computes area independent of winding order", () => {
    expect(polygonArea(square(0, 0, 1))).toBeCloseTo(1);
    expect(polygonArea([...square(0, 0, 0.5)].reverse())).toBeCloseTo(0.25);
  });
  it("detects proper, touching and collinear-overlap intersections", () => {
    expect(segmentsIntersect({ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }, { x: 1, y: 0 })).toBe(true);
    expect(segmentsIntersect({ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 })).toBe(true);
    expect(segmentsIntersect({ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 0, y: 1 }, { x: 1, y: 1 })).toBe(false);
  });
  it("flags a bow-tie as self-intersecting and accepts convex and concave polygons", () => {
    expect(isSelfIntersecting([{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }, { x: 0.5, y: 0.1 }, { x: 0.1, y: 0.5 }])).toBe(true);
    expect(isSelfIntersecting(square(0.1, 0.1))).toBe(false);
    expect(isSelfIntersecting([{ x: 0.1, y: 0.1 }, { x: 0.9, y: 0.1 }, { x: 0.5, y: 0.4 }, { x: 0.9, y: 0.9 }, { x: 0.1, y: 0.9 }])).toBe(false);
  });
  it("detects overlap, containment and separation", () => {
    expect(polygonsOverlap(square(0.1, 0.1), square(0.2, 0.2))).toBe(true);
    expect(polygonsOverlap(square(0.1, 0.1, 0.8), square(0.3, 0.3, 0.1))).toBe(true); // fully contained
    expect(polygonsOverlap(square(0.1, 0.1), square(0.6, 0.6))).toBe(false);
  });
});

describe("polygonProblem (same order and rules as the server)", () => {
  it("reports each invalid shape with the server's code", () => {
    expect(polygonProblem([{ x: 0.1, y: 0.1 }, { x: 0.2, y: 0.2 }])).toBe("TOO_FEW_POINTS");
    expect(polygonProblem([{ x: 0.1, y: 0.1 }, { x: 1.2, y: 0.2 }, { x: 0.3, y: 0.3 }])).toBe("OUT_OF_BOUNDS");
    expect(polygonProblem([{ x: 0.1, y: 0.1 }, { x: 0.1, y: 0.1 }, { x: 0.2, y: 0.2 }])).toBe("DEGENERATE_POLYGON");
    expect(polygonProblem([{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }, { x: 0.5, y: 0.1 }, { x: 0.1, y: 0.5 }])).toBe("SELF_INTERSECTING"); // not mislabelled as degenerate
    expect(polygonProblem([{ x: 0.1, y: 0.1 }, { x: 0.2, y: 0.2 }, { x: 0.3, y: 0.3 }])).toBe("DEGENERATE_POLYGON");
    expect(polygonProblem([{ x: 0.1, y: 0.1 }, { x: 0.1001, y: 0.1 }, { x: 0.1, y: 0.1001 }])).toBe("DEGENERATE_POLYGON");
    expect(polygonProblem(square(0.1, 0.1))).toBeNull();
  });
});

describe("validateRegions", () => {
  it("blocks on invalid polygons and duplicate keys, but only warns about overlaps", () => {
    const result = validateRegions([region("a", square(0.1, 0.1)), region("b", square(0.2, 0.2)), region("c", square(0.6, 0.6)), region("c", square(0.7, 0.7)), region("d", [{ x: 0.1, y: 0.1 }, { x: 0.2, y: 0.2 }, { x: 0.3, y: 0.3 }])]);
    expect(result.errors.map((issue) => issue.code).sort()).toEqual(["DEGENERATE_POLYGON", "DUPLICATE_REGION_KEY"]);
    expect(result.warnings.map((issue) => issue.region_keys)).toContainEqual(["a", "b"]);
    expect(result.warnings.every((issue) => issue.code === "REGIONS_OVERLAP")).toBe(true);
  });
  it("is clean for an empty or well-formed layout", () => {
    expect(validateRegions([])).toEqual({ errors: [], warnings: [] });
    expect(validateRegions([region("a", square(0.1, 0.1)), region("b", square(0.6, 0.6))])).toEqual({ errors: [], warnings: [] });
  });
});
