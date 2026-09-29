// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../services/api";
import { SessionComparePage } from "./SessionComparePage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const get = vi.mocked(api.get), post = vi.mocked(api.post);
// jsdom has no ResizeObserver; Recharts' ResponsiveContainer needs one.
class FakeResizeObserver { observe() {} unobserve() {} disconnect() {} }
vi.stubGlobal("ResizeObserver", FakeResizeObserver);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const SESSIONS = [
  { id: 101, name: "Lecture A", status: "COMPLETED", source_type: "VIDEO", classroom_id: 1, course_id: null, activity_context: "LECTURE", created_at: "2026-09-01T10:00:00Z", duration: 1800 },
  { id: 102, name: "Lecture B", status: "COMPLETED", source_type: "VIDEO", classroom_id: 1, course_id: null, activity_context: "LECTURE", created_at: "2026-09-02T10:00:00Z", duration: 1700 },
  { id: 103, name: "Discussion C", status: "COMPLETED", source_type: "LIVE", classroom_id: 2, course_id: null, activity_context: "GROUP_DISCUSSION", created_at: "2026-09-03T10:00:00Z", duration: 1200 },
];

function mockListEndpoints() {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u.includes("/v1/sessions")) return { data: { items: SESSIONS, page: 1, pages: 1, total: SESSIONS.length } } as any;
    if (u.includes("/v1/classrooms")) return { data: [{ id: 1, name: "Room 204" }, { id: 2, name: "Room 305" }] } as any;
    if (u.includes("/v1/courses")) return { data: [] } as any;
    return { data: [] } as any;
  });
}

function comparisonResponse(overrides: Partial<any> = {}) {
  return {
    status: "AVAILABLE",
    sessions: [
      { session_id: 101, name: "Lecture A", created_at: "2026-09-01T10:00:00Z", duration: 1800, context: "LECTURE", classroom_id: 1, course_id: null, source_type: "VIDEO", status: "COMPLETED", coverage: 0.9, confidence: 0.8, methodology_version: "1.0", metric_results: {} },
      { session_id: 102, name: "Lecture B", created_at: "2026-09-02T10:00:00Z", duration: 1700, context: "LECTURE", classroom_id: 1, course_id: null, source_type: "VIDEO", status: "COMPLETED", coverage: 0.7, confidence: 0.6, methodology_version: "1.0", metric_results: {} },
    ],
    metric_results: {
      occupancy: {
        "101": { value: 0, available: true, reason: null, coverage: 1, confidence: 0.9, valid_observations: 1, total_observations: 1 },
        "102": { value: 5, available: true, reason: null, coverage: 1, confidence: 0.9, valid_observations: 1, total_observations: 1 },
      },
      observable_participation: {
        "101": { value: null, available: false, reason: "insufficient_valid_observations", coverage: 0.1, confidence: null, valid_observations: 1, total_observations: 10 },
        "102": { value: 74.2, available: true, reason: null, coverage: 0.82, confidence: 0.71, valid_observations: 8, total_observations: 10 },
      },
      peak_occupancy: {}, unoccupied_capacity: {}, visual_orientation: {}, prolonged_eye_closure: {},
      possible_fatigue: {}, yawning: {}, raised_hands: {}, frame_quality: {},
    },
    compatibility: { compatible: true, notices: [] },
    warnings: [],
    ...overrides,
  };
}

function renderPage(initialPath = "/compare") {
  return render(<MemoryRouter initialEntries={[initialPath]}><SessionComparePage /></MemoryRouter>);
}

describe("SessionComparePage", () => {
  it("initializes selection from query parameters", async () => {
    mockListEndpoints();
    post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/analytics/compare", expect.objectContaining({ session_ids: [101, 102] })));
    expect(await screen.findByText("Selected sessions (2/5)")).toBeTruthy();
  });

  it("ignores invalid query parameters instead of crashing", async () => {
    mockListEndpoints();
    renderPage("/compare?session_ids=abc,-1,");
    expect(await screen.findByText("Selected sessions (0/5)")).toBeTruthy();
    expect(screen.getAllByText(/Select at least two sessions/).length).toBeGreaterThan(0);
  });

  it("shows the insufficient-selection state with fewer than two sessions", async () => {
    mockListEndpoints();
    renderPage();
    await screen.findByText("Lecture A"); // candidate list has loaded
    expect(screen.getAllByText(/Select at least two sessions/).length).toBeGreaterThan(0);
    expect(post).not.toHaveBeenCalled();
  });

  it("adds sessions from the candidate list, preventing duplicates, up to five", async () => {
    mockListEndpoints();
    post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage();
    await screen.findByText("Lecture A");
    fireEvent.click(screen.getAllByText("Add")[0]);
    await waitFor(() => expect(screen.getByText("Selected sessions (1/5)")).toBeTruthy());
    // The just-added session must disappear from the candidate list (no duplicate selection).
    expect(screen.queryAllByText("Lecture A").length).toBeGreaterThan(0); // still shown in the "selected" summary card
  });

  it("shows loading, then the comparison table and chart", async () => {
    mockListEndpoints();
    post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText("Comparison table")).toBeTruthy();
  });

  it("displays a genuine zero, not Unavailable, in the comparison table", async () => {
    mockListEndpoints();
    post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    await screen.findByText("Comparison table");
    expect(screen.getByText(/^0 people/)).toBeTruthy(); // occupancy for session 101 is a genuine 0
  });

  it("displays an unavailable reason instead of a blank or zero", async () => {
    mockListEndpoints();
    post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    await screen.findByText("Comparison table");
    expect(screen.getByText(/Insufficient evidence — 1 of 10 observations were valid/)).toBeTruthy();
  });

  it("formats a percentage metric with a percent sign and a count metric without one", async () => {
    mockListEndpoints();
    post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    await screen.findByText("Comparison table");
    expect(screen.getByText(/74\.2%/)).toBeTruthy(); // percent metric (observable_participation)
    expect(screen.getByText(/^5 people/)).toBeTruthy(); // count metric (occupancy), no percent sign
  });

  it("shows compatibility warnings before the charts", async () => {
    mockListEndpoints();
    post.mockResolvedValue({
      data: comparisonResponse({ compatibility: { compatible: false, notices: [{ level: "warning", code: "DIFFERENT_ACTIVITY_CONTEXTS", message: "Selected sessions use different activity contexts." }] } }),
    } as any);
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText("Selected sessions use different activity contexts.")).toBeTruthy();
  });

  it("shows an error state when the comparison request fails", async () => {
    mockListEndpoints();
    post.mockRejectedValue({ response: { status: 400, data: { detail: { error: { message: "Unsupported comparison metric." } } } } });
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText("Unsupported comparison metric.")).toBeTruthy();
  });

  it("shows an unauthorized state on a 403 response", async () => {
    mockListEndpoints();
    post.mockRejectedValue({ response: { status: 403 } });
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText(/not authorized to compare/)).toBeTruthy();
  });

  it("renders a CSV export link once a comparison is available", async () => {
    mockListEndpoints();
    post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    await screen.findByText("Comparison table");
    const link = screen.getByText("Export CSV").closest("a");
    expect(link?.getAttribute("href")).toContain("/api/v1/analytics/compare/export?session_ids=101,102");
  });
});

describe("SessionComparePage Phase 3C additions", () => {
  const withEvents = () => {
    const base = comparisonResponse();
    base.sessions[0] = { ...base.sessions[0], event_counts: { HAND_RAISED: 4, YAWNING: 1 } } as any;
    base.sessions[1] = { ...base.sessions[1], event_counts: { HAND_RAISED: 2 } } as any;
    return base;
  };
  const regionData = (layoutId: number | null, status = "CALIBRATED") => (id: number) => ({ session_id: id, status, layout_id: layoutId, layout_version: 3, regions: layoutId ? [{ region_id: "front", name: "Front row", estimated_unique_tracks: id === 101 ? 6 : 8, observation_count: 10, raised_hand_observations: 1, visual_coverage: 80 }] : [] });
  function mockWithRegions(regions: (id: number) => any) {
    get.mockImplementation(async (url: any) => {
      const u = String(url);
      const match = u.match(/\/v1\/sessions\/(\d+)\/regions/);
      if (match) return { data: regions(Number(match[1])) } as any;
      if (u.includes("/v1/sessions")) return { data: { items: SESSIONS, page: 1, pages: 1, total: SESSIONS.length } } as any;
      if (u.includes("/v1/classrooms")) return { data: [{ id: 1, name: "Room 204" }] } as any;
      return { data: [] } as any;
    });
  }

  it("compares stored event frequencies per type, with a table alternative and zero for a type a session lacks", async () => {
    mockListEndpoints(); post.mockResolvedValue({ data: withEvents() } as any);
    renderPage("/compare?session_ids=101,102");
    const table = await screen.findByRole("table", { name: "Event counts by type" });
    const yawn = within(table).getByText("YAWNING").closest("tr")!;
    expect(within(yawn).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["1", "0"]); // genuine zero for the session with no yawning events
    expect(within(table).getByText("HAND RAISED").closest("tr")!.textContent).toContain("42");
    expect(screen.getByRole("img", { name: /Grouped bar chart of stored event counts/ })).toBeTruthy();
    expect(screen.getByText(/Events are observations, not judgements/)).toBeTruthy();
  });

  it("says so when no session has stored events", async () => {
    mockListEndpoints(); post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText("No stored events for the selected sessions.")).toBeTruthy();
  });

  it("compares regions only when every session used the same calibrated layout", async () => {
    mockWithRegions(regionData(4)); post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    const table = await screen.findByRole("table", { name: /Anonymous unique tracks per region \(layout version 3\)/ });
    expect(within(table).getByText("Front row").closest("tr")!.textContent).toContain("68");
  });

  it("refuses to compare regions across different layouts and explains why, without inventing values", async () => {
    mockWithRegions((id) => regionData(id === 101 ? 4 : 5)(id)); post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText("Region comparison is not available")).toBeTruthy();
    expect(screen.getByText(/used different classroom layouts, so regions are not aligned\. No region values were estimated/)).toBeTruthy();
    expect(screen.queryByRole("table", { name: /per region/ })).toBeNull();
  });

  it("refuses region comparison when a session has no calibrated layout", async () => {
    mockWithRegions((id) => (id === 101 ? regionData(4)(id) : { session_id: id, status: "UNCALIBRATED", regions: [] })); post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText(/at least one selected session has no calibrated classroom layout/)).toBeTruthy();
  });

  it("orders compatibility notices with warnings first, and reports a comparable selection", async () => {
    mockListEndpoints();
    post.mockResolvedValue({ data: comparisonResponse({ compatibility: { compatible: false, notices: [{ level: "info", code: "MISSING_HISTORICAL_EVIDENCE", message: "One session predates tracking." }, { level: "warning", code: "DIFFERENT_CLASSROOMS", message: "Different classrooms." }] } }) } as any);
    renderPage("/compare?session_ids=101,102");
    const section = (await screen.findByText("Compatibility")).closest("section")!;
    expect(within(section).getByText("Compare with caution")).toBeTruthy();
    expect(within(section).getByText("1 warning · 1 note")).toBeTruthy();
    const messages = within(section).getAllByRole("listitem").map((item) => item.textContent);
    expect(messages).toEqual(["Different classrooms.", "One session predates tracking."]);
    cleanup(); vi.resetAllMocks(); mockListEndpoints(); post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    const clean = (await screen.findByText("Compatibility")).closest("section")!;
    expect(within(clean).getByText("Comparable")).toBeTruthy();
    expect(within(clean).getByText("No compatibility concerns were found for these sessions.")).toBeTruthy();
  });

  it("flags partial and insufficient evidence explicitly", async () => {
    mockListEndpoints(); post.mockResolvedValue({ data: comparisonResponse({ status: "PARTIAL_EVIDENCE" }) } as any);
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText(/Partial evidence\./)).toBeTruthy();
    cleanup(); vi.resetAllMocks(); mockListEndpoints(); post.mockResolvedValue({ data: comparisonResponse({ status: "INSUFFICIENT_EVIDENCE" }) } as any);
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText(/nothing was converted to zero/)).toBeTruthy();
  });

  it("charts coverage, confidence and valid observations with labelled charts and one evidence table", async () => {
    mockListEndpoints(); post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    const table = await screen.findByRole("table", { name: "Evidence quality table" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Session", "Coverage", "Confidence", "Valid observations", "Total observations", "Status"]);
    const first = within(table).getByText("Lecture A").closest("tr")!;
    expect(within(first).getAllByRole("cell").slice(0, 2).map((cell) => cell.textContent)).toEqual(["90%", "80%"]);
    for (const name of [/evidence coverage per session/, /evidence confidence per session/, /valid observations per session/]) expect(screen.getByRole("img", { name })).toBeTruthy();
  });

  it("uses a captioned comparison table with row headers and responsive cell labels for all ten metrics", async () => {
    mockListEndpoints(); post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    const table = await screen.findByRole("table", { name: /Every compared metric for each selected session/ });
    expect(within(table).getAllByRole("rowheader").length).toBe(10);
    expect(within(table).getAllByRole("cell")[0].getAttribute("data-th")).toBe("Lecture A");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Metric", "Lecture A", "Lecture B"]);
  });

  it("removes one session or clears all, and stops comparing below two sessions", async () => {
    mockListEndpoints(); post.mockResolvedValue({ data: comparisonResponse() } as any);
    renderPage("/compare?session_ids=101,102");
    await screen.findByText("Comparison table");
    fireEvent.click(screen.getByLabelText("Remove Lecture B"));
    expect(await screen.findByText("Selected sessions (1/5)")).toBeTruthy();
    expect(screen.queryByText("Comparison table")).toBeNull();
    expect(screen.getAllByText(/Select at least two sessions/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Clear all"));
    expect(await screen.findByText("Selected sessions (0/5)")).toBeTruthy();
  });

  it("filters candidates by date range and validates a reversed range", async () => {
    mockListEndpoints(); renderPage();
    await screen.findByText("Lecture A");
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-02" } });
    expect(screen.queryByText("Lecture A")).toBeNull();
    expect(screen.getByText("Lecture B")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-02" } });
    expect(screen.queryByText("Discussion C")).toBeNull();
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-01" } });
    expect(screen.getByText("End date must not be before the start date.")).toBeTruthy();
    fireEvent.click(screen.getByText("Reset filters"));
    expect(await screen.findByText("Lecture A")).toBeTruthy();
  });

  it("re-queries the server for another data source and never mixes test data into REAL", async () => {
    mockListEndpoints(); renderPage();
    await screen.findByText("Lecture A");
    const sessionCalls = () => get.mock.calls.filter(([url]) => String(url).includes("/v1/sessions"));
    expect((sessionCalls().at(-1)?.[1] as any).params).toMatchObject({ status: "COMPLETED", mode: "REAL" });
    expect((sessionCalls().at(-1)?.[1] as any).params.include_tests).toBeUndefined();
    fireEvent.change(screen.getByLabelText("Data source filter"), { target: { value: "TEST" } });
    await waitFor(() => expect((sessionCalls().at(-1)?.[1] as any).params).toMatchObject({ include_tests: true }));
    expect((sessionCalls().at(-1)?.[1] as any).params.mode).toBeUndefined();
  });

  it("offers retry for a server error but not for a rejected request", async () => {
    mockListEndpoints(); post.mockRejectedValue({ response: { status: 500, data: { error: { message: "Comparison backend down", request_id: "r-1" } } } });
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText("Comparison backend down")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
    cleanup(); vi.resetAllMocks(); mockListEndpoints(); post.mockRejectedValue({ response: { status: 400, data: { error: { message: "Unsupported comparison metric." } } } });
    renderPage("/compare?session_ids=101,102");
    expect(await screen.findByText("Unsupported comparison metric.")).toBeTruthy();
    expect(screen.queryByText("Retry")).toBeNull();
  });

  it("shows the privacy notice", async () => {
    mockListEndpoints(); renderPage();
    expect(await screen.findByText(/does not identify students/)).toBeTruthy();
  });

  it("renders repeated compatibility notice codes without duplicate-key warnings", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});   // scoped to this test, restored below
    try {
      mockListEndpoints();
      post.mockResolvedValue({ data: comparisonResponse({ compatibility: { compatible: false, notices: [
        { level: "warning", code: "METRIC_UNAVAILABLE", message: "Occupancy is unavailable for session 102." },
        { level: "warning", code: "METRIC_UNAVAILABLE", message: "Frame quality is unavailable for session 101." },
        { level: "info", code: "METRIC_UNAVAILABLE", message: "Audio quality is not processed." },
      ] } }) } as any);
      renderPage("/compare?session_ids=101,102");
      const section = (await screen.findByText("Compatibility")).closest("section")!;
      expect(within(section).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
        "Occupancy is unavailable for session 102.", "Frame quality is unavailable for session 101.", "Audio quality is not processed.",
      ]);
      const reactWarnings = consoleError.mock.calls.map((call) => call.map(String).join(" ")).filter((text) => /same key|unique "key"/i.test(text));
      expect(reactWarnings).toEqual([]);
    } finally {
      consoleError.mockRestore();
    }
  });
});
