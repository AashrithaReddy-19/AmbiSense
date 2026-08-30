// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { Activity } from "lucide-react";
import { describe, expect, it } from "vitest";
import { MetricCard } from "./MetricCard";
describe("MetricCard availability", () => {
  it("shows unavailable rather than a false zero", () => {
    render(
      <MetricCard
        label="Visual orientation"
        value={0}
        icon={Activity}
        metric={{
          metric: "visual_orientation",
          value: null,
          unit: "percent",
          status: "INSUFFICIENT_EVIDENCE",
          confidence: null,
          confidence_label: "Insufficient evidence",
          coverage: {
            valid_observations: 0,
            eligible_observations: 5,
            ratio: 0,
          },
          limitations: ["No landmarks"],
        }}
      />,
    );
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.getByText(/INSUFFICIENT EVIDENCE/)).toBeTruthy();
  });
});
