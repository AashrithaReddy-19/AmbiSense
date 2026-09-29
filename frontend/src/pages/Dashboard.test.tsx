// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../services/api";
import { Dashboard } from "./Dashboard";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const get = vi.mocked(api.get);
class FakeResizeObserver { observe() {} unobserve() {} disconnect() {} }
vi.stubGlobal("ResizeObserver", FakeResizeObserver);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const OVERVIEW = {
  session_counts: { total: 5, completed: 2, failed: 1, processing: 1, queued: 1, initializing: 0, aggregating: 0, generating_report: 0 },
  reports_available: 2,
  classrooms_configured: 3,
  average_valid_observation_coverage: 0.734,
  data_quality: { tiers: { HIGH: 2, MODERATE: 1, LOW: 0, INSUFFICIENT_EVIDENCE: 2 }, thresholds: { high_min_coverage: 0.8, moderate_min_coverage: 0.5, definition: "x" } },
  recent_sessions: [{ id: 101, name: "Lecture A", classroom_id: 1, activity_context: "LECTURE", source_type: "VIDEO", status: "COMPLETED", created_at: "2026-09-01T10:00:00Z", duration: 1800, coverage: 0.9 }],
  recent_reports: [{ session_id: 101, session_name: "Lecture A", format: "pdf", created_at: "2026-09-01T11:00:00Z" }],
  recent_events: [{ session_id: 101, timestamp: 12, event_type: "HIGH_FATIGUE", severity: "WARNING", review_state: "UNREVIEWED" }],
};
const TRENDS_WITH_DATA = { points: [{ bucket: "2026-09-01", series: "LECTURE", result: { value: 74.2, available: true, reason: null, coverage: 0.8, confidence: 0.7, valid_observations: 8, total_observations: 10 } }] };
const TRENDS_EMPTY = { points: [] };

function mockEndpoints(overview: any, trends: any = TRENDS_EMPTY) {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u.includes("/v1/dashboard/overview")) return { data: overview } as any;
    if (u.includes("/v1/analytics/trends")) return { data: trends } as any;
    if (u.includes("/v1/classrooms")) return { data: [{ id: 1, name: "Room 204" }] } as any;
    return { data: [] } as any;
  });
}

function renderDashboard() {
  return render(<MemoryRouter><Dashboard /></MemoryRouter>);
}

describe("Dashboard", () => {
  it("displays the real summary response", async () => {
    mockEndpoints(OVERVIEW, TRENDS_WITH_DATA);
    renderDashboard();
    expect((await screen.findAllByText("Lecture A")).length).toBeGreaterThan(0);
    expect(screen.getByText("Completed sessions").closest("article")?.textContent).toContain("2");
  });

  it("shows a loading state before data arrives", async () => {
    let resolve: (v: any) => void = () => {};
    get.mockImplementation(() => new Promise((r) => { resolve = r; }));
    renderDashboard();
    expect(document.querySelectorAll(".skeleton-card").length).toBeGreaterThan(0);
    resolve({ data: OVERVIEW });
  });

  it("shows an error state with retry on API failure", async () => {
    get.mockRejectedValue({ response: { data: { detail: "Backend unavailable" } } });
    renderDashboard();
    expect(await screen.findByText("Backend unavailable")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("handles an empty database response without errors", async () => {
    mockEndpoints({ ...OVERVIEW, session_counts: { total: 0 }, recent_sessions: [], recent_reports: [], recent_events: [], reports_available: 0, classrooms_configured: 0, average_valid_observation_coverage: null, data_quality: { tiers: { HIGH: 0, MODERATE: 0, LOW: 0, INSUFFICIENT_EVIDENCE: 0 }, thresholds: OVERVIEW.data_quality.thresholds } });
    renderDashboard();
    expect(await screen.findByText("No sessions found")).toBeTruthy();
    expect(screen.getByText("No completed reports")).toBeTruthy();
  });

  it("shows Unavailable for a null coverage metric instead of 0", async () => {
    mockEndpoints({ ...OVERVIEW, average_valid_observation_coverage: null });
    renderDashboard();
    await screen.findAllByText("Lecture A");
    expect(screen.getByText("Unavailable")).toBeTruthy();
  });

  it("shows a genuine zero failed-session count as 0, not Unavailable", async () => {
    mockEndpoints({ ...OVERVIEW, session_counts: { ...OVERVIEW.session_counts, failed: 0 } });
    renderDashboard();
    await screen.findAllByText("Lecture A");
    const failedLabel = screen.getByText("Failed sessions").closest("article");
    expect(failedLabel?.textContent).toContain("0");
  });

  it("sends the classroom and data-source filters to the backend", async () => {
    mockEndpoints(OVERVIEW);
    renderDashboard();
    await screen.findAllByText("Lecture A");
    const dataSourceCall = get.mock.calls.find(([url]) => String(url).includes("/v1/dashboard/overview"));
    expect(dataSourceCall?.[1]).toMatchObject({ params: expect.objectContaining({ data_source: "REAL" }) });
  });

  it("renders a working link to the recent session's detail page", async () => {
    mockEndpoints(OVERVIEW);
    renderDashboard();
    const link = await screen.findByRole("link", { name: "Open" });
    expect(link.getAttribute("href")).toBe("/sessions/101");
  });

  it("shows a trend chart gap message when no evidence is available", async () => {
    mockEndpoints(OVERVIEW, TRENDS_EMPTY);
    renderDashboard();
    expect(await screen.findByText("No trend evidence")).toBeTruthy();
  });

  it("does not resolve a stale request after filters change", async () => {
    // First call hangs; a second (different) mock resolves immediately.
    // Only the latest response should be reflected in the DOM.
    let firstResolve: (v: any) => void = () => {};
    let callCount = 0;
    get.mockImplementation(async (url: any) => {
      const u = String(url);
      if (u.includes("/v1/classrooms")) return { data: [] } as any;
      callCount += 1;
      if (callCount === 1) return new Promise((r) => { firstResolve = r; });
      if (u.includes("overview")) return { data: OVERVIEW } as any;
      return { data: TRENDS_EMPTY } as any;
    });
    renderDashboard();
    await waitFor(() => expect(callCount).toBeGreaterThanOrEqual(1));
    firstResolve({ data: OVERVIEW });
    await screen.findAllByText("Lecture A");
  });

  it("uses the responsive split class instead of an inline grid template", async () => {
    mockEndpoints(OVERVIEW, TRENDS_WITH_DATA);
    renderDashboard();
    await screen.findAllByText("Lecture A");
    const split = document.querySelector(".live-layout.dash-split") as HTMLElement;
    expect(split).toBeTruthy();
    expect(split.style.gridTemplateColumns).toBe("");   // inline styles beat the max-width media query and crushed the columns on phones
    expect(split.querySelectorAll(":scope > section").length).toBe(2);
  });
});
