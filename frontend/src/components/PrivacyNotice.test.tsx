// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { METRIC_DEFINITIONS } from "../content/metricDefinitions";
import { MetricExplainer, NOTICE_ANONYMOUS, NOTICE_HIGH_IMPACT, NOTICE_NOT_VALIDATED, NOTICE_NO_ACCURACY, NOTICE_OCCUPANCY, PrivacyNotice } from "./PrivacyNotice";

afterEach(cleanup);

describe("PrivacyNotice", () => {
  it("uses the exact required wording", () => {
    expect(NOTICE_ANONYMOUS).toBe("AmbiSense uses anonymous session-local tracking and does not identify students.");
    expect(NOTICE_OCCUPANCY).toBe("Occupancy is an estimate and is not verified attendance.");
    expect(NOTICE_HIGH_IMPACT).toBe("These observational indicators must not be used as the sole basis for grading, discipline, attendance, or other high-impact decisions.");
    expect(NOTICE_NOT_VALIDATED).toBe("Not validated on real classroom footage.");
    expect(NOTICE_NO_ACCURACY).toBe("No verified accuracy or fairness result is currently available.");
  });
  it("shows all three statements in the full variant and the validation status on request", () => {
    const { rerender } = render(<PrivacyNotice />);
    const note = screen.getByRole("note");
    for (const text of [NOTICE_ANONYMOUS, NOTICE_OCCUPANCY, NOTICE_HIGH_IMPACT]) expect(within(note).getByText(text)).toBeTruthy();
    expect(within(note).queryByText(new RegExp(NOTICE_NOT_VALIDATED))).toBeNull();
    rerender(<PrivacyNotice showValidation />);
    expect(screen.getByText(new RegExp(NOTICE_NOT_VALIDATED))).toBeTruthy();
    expect(screen.getByText(new RegExp(NOTICE_NO_ACCURACY))).toBeTruthy();
  });
  it("keeps the responsible-use statement reachable in the compact variant", () => {
    render(<PrivacyNotice variant="compact" showValidation />);
    expect(screen.getByText(new RegExp(NOTICE_ANONYMOUS))).toBeTruthy();
    expect(screen.getByText("Responsible use")).toBeTruthy();
    expect(screen.getByText(NOTICE_HIGH_IMPACT)).toBeTruthy();
    expect(screen.getByText(new RegExp(NOTICE_NOT_VALIDATED))).toBeTruthy();
  });
  it("is not rendered as an <aside>, which the shell styles as the fixed navigation", () => {
    const { container } = render(<PrivacyNotice />);
    expect(container.querySelector("aside")).toBeNull();
  });
});

describe("MetricExplainer and metric definitions", () => {
  it("explains meaning, evidence, coverage, confidence, failure reasons, limitations and contexts", () => {
    render(<MetricExplainer metric="observable_participation" />);
    expect(screen.getByText(/What does “Observable participation indicator” mean\?/)).toBeTruthy();
    for (const heading of ["Meaning", "Required evidence", "Coverage", "Confidence", "Why it can be unavailable", "Limitations", "Activity contexts"]) expect(screen.getByText(heading)).toBeTruthy();
    expect(screen.getByText(/not how much anyone is learning or participating/)).toBeTruthy();
    expect(screen.getByText(/no one was detected in frame/)).toBeTruthy(); // reason codes are shown in plain language
  });
  it("renders nothing for an unknown metric", () => {
    const { container } = render(<MetricExplainer metric="nonexistent" />);
    expect(container.innerHTML).toBe("");
  });
  it("defines every dashboard metric without prohibited claims", () => {
    for (const key of ["occupancy", "observable_participation", "visual_orientation", "possible_fatigue", "prolonged_eye_closure", "yawning", "raised_hands", "frame_quality", "camera_quality", "audio_quality", "question_count", "fusion", "peak_occupancy", "unoccupied_capacity"]) {
      const definition = METRIC_DEFINITIONS[key];
      expect(definition, key).toBeTruthy();
      expect(definition.meaning.length).toBeGreaterThan(20);
      expect(definition.limitations.length).toBeGreaterThan(0);
      expect(definition.failureReasons.length).toBeGreaterThan(0);
    }
    const text = JSON.stringify(METRIC_DEFINITIONS).toLowerCase();
    for (const banned of ["student is attentive", "student is disengaged", "student is sleeping", "emotion detected", "cheating detected", "student performance"]) expect(text).not.toContain(banned);
    expect(METRIC_DEFINITIONS.possible_fatigue.limitations.join(" ")).toMatch(/Never infer that a person is sleeping or disengaged/); // the only mention is a warning against the inference
    expect(METRIC_DEFINITIONS.occupancy.limitations.join(" ")).toMatch(/not verified attendance/);
  });
});
