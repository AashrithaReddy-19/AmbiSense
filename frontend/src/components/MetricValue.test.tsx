// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { formatMetricAvailability, MetricValue, readableReason } from "./MetricValue";
import type { MetricAvailability } from "../types";

const available = (overrides: Partial<MetricAvailability> = {}): MetricAvailability => ({
  value: 74.2, available: true, reason: null, coverage: 0.82, confidence: 0.71,
  valid_observations: 8, total_observations: 10, ...overrides,
});
const unavailable = (overrides: Partial<MetricAvailability> = {}): MetricAvailability => ({
  value: null, available: false, reason: "facial_landmarks_unavailable", coverage: 0, confidence: null,
  valid_observations: 0, total_observations: 5, ...overrides,
});

describe("formatMetricAvailability", () => {
  it("displays a genuine zero, not Unavailable", () => {
    const text = formatMetricAvailability(available({ value: 0, coverage: null, confidence: null }), { kind: "count", noun: "people" });
    expect(text).toBe("0 people");
    expect(text).not.toMatch(/Unavailable/);
  });

  it("formats an available percentage with coverage and confidence", () => {
    expect(formatMetricAvailability(available())).toBe("74.2% · Coverage 82% · Confidence 71%");
  });

  it("formats an available count without a percent sign", () => {
    expect(formatMetricAvailability(available({ value: 3, coverage: null, confidence: null }), { kind: "count", noun: "raised hands" }))
      .toBe("3 raised hands");
  });

  it("shows a readable reason when unavailable", () => {
    expect(formatMetricAvailability(unavailable())).toBe("Unavailable — facial landmarks were not detected");
  });

  it("shows valid/total counts for insufficient evidence", () => {
    const text = formatMetricAvailability(unavailable({ reason: "insufficient_valid_observations", valid_observations: 3, total_observations: 20 }));
    expect(text).toBe("Insufficient evidence — 3 of 20 observations were valid");
  });

  it("never renders a bare percent sign for a missing value", () => {
    const text = formatMetricAvailability(unavailable());
    expect(text).not.toBe("—%");
    expect(text).not.toContain("—%");
  });

  it("does not fall back to a hard-coded number for a missing metric", () => {
    expect(formatMetricAvailability(null)).toBe("Unavailable");
    expect(formatMetricAvailability(undefined)).toBe("Unavailable");
  });

  it("falls back to a safe generic message for an unrecognized reason code", () => {
    // Simulates an older frontend build receiving a reason code added later
    // on the backend - must not crash and must not claim a specific cause
    // it cannot actually explain.
    const text = readableReason("some_future_reason_code_not_yet_known" as never);
    expect(text).toBe("this metric is currently unavailable");
  });

  it("handles a metric object missing the newer fields safely (compatibility period)", () => {
    const legacyShaped = { value: 12, available: true } as MetricAvailability;
    expect(() => formatMetricAvailability(legacyShaped, { kind: "count" })).not.toThrow();
    expect(formatMetricAvailability(legacyShaped, { kind: "count" })).toBe("12");
  });
});

describe("MetricValue component", () => {
  it("renders available and unavailable states without throwing", () => {
    render(<MetricValue metric={available()} label="Observable participation" />);
    expect(screen.getByText("74.2% · Coverage 82% · Confidence 71%")).toBeTruthy();
    render(<MetricValue metric={unavailable()} label="Visual orientation" />);
    expect(screen.getByText("Unavailable — facial landmarks were not detected")).toBeTruthy();
  });
});
