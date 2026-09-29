// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider, useTheme } from "./ThemeContext";

afterEach(() => { cleanup(); localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });

function Probe() {
  const { mode, resolved, setMode } = useTheme();
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="resolved">{resolved}</span>
      <button onClick={() => setMode("light")}>light</button>
      <button onClick={() => setMode("dark")}>dark</button>
      <button onClick={() => setMode("system")}>system</button>
    </div>
  );
}

function mockMatchMedia(prefersDark: boolean) {
  const listeners: Array<(e: MediaQueryListEvent) => void> = [];
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("dark") && prefersDark,
    media: query,
    addEventListener: (_: string, cb: any) => listeners.push(cb),
    removeEventListener: vi.fn(),
  })));
  return listeners;
}

describe("ThemeContext", () => {
  beforeEach(() => mockMatchMedia(false));

  it("defaults to system mode and resolves to light when the OS prefers light", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("mode").textContent).toBe("system");
    expect(screen.getByTestId("resolved").textContent).toBe("light");
  });

  it("applies the dark theme and sets data-theme on the document element", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    fireEvent.click(screen.getByText("dark"));
    expect(screen.getByTestId("resolved").textContent).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("applies the light theme explicitly", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "light" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("persists the theme preference across remounts", () => {
    const { unmount } = render(<ThemeProvider><Probe /></ThemeProvider>);
    fireEvent.click(screen.getByText("dark"));
    unmount();
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("mode").textContent).toBe("dark");
    expect(localStorage.getItem("ambisense_theme")).toBe("dark");
  });

  it("system mode removes the explicit data-theme attribute and follows the OS", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    fireEvent.click(screen.getByText("dark"));
    fireEvent.click(screen.getByText("system"));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("responds to OS theme changes while in system mode", () => {
    const listeners = mockMatchMedia(false);
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("resolved").textContent).toBe("light");
    act(() => { listeners.forEach((cb) => cb({ matches: true } as MediaQueryListEvent)); });
    expect(screen.getByTestId("resolved").textContent).toBe("dark");
  });
});
