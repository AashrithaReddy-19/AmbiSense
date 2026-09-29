import { describe, expect, it } from "vitest";
import { ACTIVITY_CONTEXTS, DATA_SOURCES, METRIC_LABELS, apiProblem, contextLabel, formatBytes, formatDateTime, formatDuration, isForbidden, percent } from "./constants";

describe("canonical option lists", () => {
  it("match the backend's activity contexts and data sources", () => {
    expect(ACTIVITY_CONTEXTS).toEqual(["LECTURE", "EXAMINATION", "GROUP_DISCUSSION", "LABORATORY", "STUDENT_PRESENTATION", "INDEPENDENT_WRITING", "READING", "VIDEO_SCREENING", "BREAK"]);
    expect(DATA_SOURCES.map((source) => source.value)).toEqual(["REAL", "DEMO", "TEST", "ALL"]);
  });
  it("uses only non-judgemental metric names", () => {
    const text = Object.values(METRIC_LABELS).join(" ").toLowerCase();
    for (const banned of ["attentive", "disengaged", "sleeping", "emotion", "cheating", "attendance", "performance"]) expect(text).not.toContain(banned);
    expect(METRIC_LABELS.occupancy).toBe("Anonymous occupancy estimate");
    expect(METRIC_LABELS.possible_fatigue).toBe("Possible fatigue indicator");
  });
});

describe("apiProblem", () => {
  const failure = (status: number, data: unknown) => ({ response: { status, data } });
  it("prefers the canonical error contract and keeps the request id", () => {
    expect(apiProblem(failure(404, { error: { code: "NOT_FOUND", message: "Session not found", request_id: "abc", details: null }, detail: "Session not found" }))).toEqual({ message: "Session not found", code: "NOT_FOUND", status: 404, requestId: "abc", details: null });
  });
  it("falls back through structured, string and validation-array details", () => {
    expect(apiProblem(failure(400, { detail: { error: { code: "INVALID_PERIOD", message: "Bad period" } } }))).toMatchObject({ message: "Bad period", code: "INVALID_PERIOD", status: 400 });
    expect(apiProblem(failure(409, { detail: "Only failed jobs can be retried" }))).toMatchObject({ message: "Only failed jobs can be retried", status: 409 });
    expect(apiProblem(failure(422, { detail: [{ msg: "Field required" }, { msg: "Too short" }] }))).toMatchObject({ message: "Field required; Too short", code: "VALIDATION_FAILED" });
    expect(apiProblem(failure(500, {}), "fallback")).toEqual({ message: "fallback", status: 500 });
  });
  it("handles network failures and detects authorization problems", () => {
    expect(apiProblem(new Error("Network Error"), "x").message).toBe("Network Error");
    expect(apiProblem(new Error("Request failed with status code 500"), "Could not load").message).toBe("Could not load");
    expect(apiProblem(undefined, "Could not load").message).toBe("Could not load");
    expect(isForbidden(apiProblem(failure(403, {})))).toBe(true);
    expect(isForbidden(apiProblem(failure(401, {})))).toBe(false);
  });
});

describe("formatters", () => {
  it("never produce malformed values", () => {
    expect(percent(0.256)).toBe("26%");
    expect(percent(0)).toBe("0%"); // a genuine zero stays zero
    for (const bad of [null, undefined, Number.NaN]) expect(percent(bad as any)).toBe("Unavailable");
    expect(formatDuration(125)).toBe("2m 5s");
    expect(formatDuration(42)).toBe("42s");
    for (const bad of [0, -1, null, undefined, Number.NaN]) expect(formatDuration(bad as any)).toBe("—");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatBytes(null)).toBe("—");
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("not a date")).toBe("—");
    expect(formatDateTime("2026-09-20T10:00:00")).not.toBe("—");
    expect(contextLabel("GROUP_DISCUSSION")).toBe("Group discussion");
  });
});
