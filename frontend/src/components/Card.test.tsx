// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { Users } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";
import { StatCard } from "./Card";

afterEach(cleanup);

describe("StatCard", () => {
  it("displays a genuine zero, not a dash or Unavailable", () => {
    render(<StatCard label="Failed sessions" value={0} icon={Users} />);
    expect(screen.getByText("0")).toBeTruthy();
    expect(screen.queryByText("Unavailable")).toBeNull();
  });

  it("displays Unavailable for a null value instead of fabricating 0", () => {
    render(<StatCard label="Average coverage" value={null} icon={Users} />);
    expect(screen.getByText("Unavailable")).toBeTruthy();
  });

  it("shows a loading skeleton instead of a value while loading", () => {
    const { container } = render(<StatCard label="Completed sessions" value={12} icon={Users} loading />);
    expect(screen.queryByText("12")).toBeNull();
    expect(container.querySelector(".skeleton")).toBeTruthy();
  });

  it("appends the unit only when a value is present", () => {
    render(<StatCard label="Coverage" value={82} unit="%" icon={Users} />);
    expect(screen.getByText("82")).toBeTruthy();
    expect(screen.getByText("%")).toBeTruthy();
  });
});
