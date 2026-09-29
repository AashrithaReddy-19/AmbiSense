// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmptyState, ErrorState, LoadingSkeleton } from "./States";

afterEach(cleanup);

describe("EmptyState", () => {
  it("renders a title, description, and an optional next action", () => {
    render(<EmptyState title="No sessions found" description="Upload a video to begin." action={<button>Upload</button>} />);
    expect(screen.getByText("No sessions found")).toBeTruthy();
    expect(screen.getByText("Upload a video to begin.")).toBeTruthy();
    expect(screen.getByText("Upload")).toBeTruthy();
  });
});

describe("ErrorState", () => {
  it("shows a safe message and an optional error code, never a stack trace", () => {
    render(<ErrorState message="The dashboard could not be loaded." code="a1b2c3" />);
    expect(screen.getByText("The dashboard could not be loaded.")).toBeTruthy();
    expect(screen.getByText(/a1b2c3/)).toBeTruthy();
  });

  it("calls onRetry when the retry action is used", () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Failed" onRetry={onRetry} />);
    fireEvent.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("LoadingSkeleton", () => {
  it("renders screen-reader-friendly loading text", () => {
    render(<LoadingSkeleton kind="card" count={3} />);
    expect(screen.getByRole("status").textContent).toMatch(/Loading/i);
  });
});
