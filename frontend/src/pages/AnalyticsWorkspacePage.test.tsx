// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../services/api";
import { AnalyticsWorkspacePage, buildChartRows, validateFilters } from "./AnalyticsWorkspacePage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const get = vi.mocked(api.get);
class FakeResizeObserver { observe() {} unobserve() {} disconnect() {} }
vi.stubGlobal("ResizeObserver", FakeResizeObserver);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const contract = (overrides: Record<string, unknown> = {}) => ({ value: 62.5, available: true, reason: null, coverage: 0.8, confidence: 0.7, valid_observations: 8, total_observations: 10, ...overrides });
const point = (bucket: string, series: string, result: any, extra: Record<string, unknown> = {}) => ({ bucket, series, context: series, methodology_version: "1.0", result, session_count: 2, contributing_sessions: result?.available ? 2 : 0, coverage: result?.coverage ?? null, confidence: result?.confidence ?? null, reason: result?.reason ?? null, ...extra });
const TRENDS = { period: "weekly", metric: "observable_participation", data_source: "REAL", aggregation_rule: "Coverage-weighted mean of available evidence.", excluded_by_filters: 0, points: [
  point("2026-W36", "LECTURE", contract({ value: 0 })),
  point("2026-W37", "LECTURE", contract({ value: null, available: false, reason: "insufficient_valid_observations", coverage: 0.1, confidence: null, valid_observations: 1 })),
  point("2026-W38", "LECTURE", contract({ value: 71.3, coverage: 0.9 })),
] };

function mockApi(trends: any = TRENDS, failure: any = null) {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u.includes("/analytics/trends")) { if (failure) throw failure; return { data: trends } as any; }
    if (u.includes("/v1/classrooms")) return { data: [{ id: 1, name: "Room 204" }] } as any;
    if (u.includes("/v1/courses")) return { data: [{ id: 3, code: "CS101", name: "Intro" }] } as any;
    return { data: [] } as any;
  });
}
function Where() { const location = useLocation(); return <output data-testid="url">{location.pathname}{location.search}</output>; }
function renderPage(path = "/analytics-workspace") {
  return render(<MemoryRouter initialEntries={[path]}><AnalyticsWorkspacePage /><Where /></MemoryRouter>);
}
const trendCalls = () => get.mock.calls.filter(([url]) => String(url).includes("/analytics/trends"));
const lastParams = () => (trendCalls().at(-1)?.[1] as any).params;

describe("validateFilters / buildChartRows (pure)", () => {
  const base = { metric: "occupancy", classroom: "", course: "", activity: "", period: "weekly", source: "REAL", start: "", end: "", min_coverage: "", min_confidence: "" };
  it("accepts valid filters and rejects reversed dates and out-of-range percentages", () => {
    expect(validateFilters(base)).toEqual({});
    expect(validateFilters({ ...base, start: "2026-09-10", end: "2026-09-01" }).end).toMatch(/before the start/);
    expect(validateFilters({ ...base, min_coverage: "101" }).min_coverage).toMatch(/0 to 100/);
    expect(validateFilters({ ...base, min_confidence: "-1" }).min_confidence).toMatch(/0 to 100/);
    expect(validateFilters({ ...base, min_coverage: "abc" }).min_coverage).toBeTruthy();
    expect(validateFilters({ ...base, min_coverage: "0" })).toEqual({});
  });
  it("keeps a genuine zero and turns unavailable evidence into a gap (null)", () => {
    const rows = buildChartRows(TRENDS.points as any);
    expect(rows.map((row) => row.LECTURE)).toEqual([0, null, 71.3]);
    expect(rows[1].LECTURE__contract.reason).toBe("insufficient_valid_observations");
  });
});

describe("AnalyticsWorkspacePage", () => {
  it("defaults to real data and sends the default filters to the backend", async () => {
    mockApi(); renderPage();
    await screen.findByText(/Trend evidence by period and series/);
    expect(lastParams()).toMatchObject({ period: "weekly", metric: "observable_participation", data_source: "REAL" });
    expect(lastParams().classroom_id).toBeUndefined();
    expect(lastParams().minimum_coverage).toBeUndefined();
  });

  it("initializes every filter from the URL and sends real filters (coverage as a fraction)", async () => {
    mockApi(); renderPage("/analytics-workspace?metric=occupancy&classroom=1&course=3&activity=EXAMINATION&period=daily&source=ALL&start=2026-09-01&end=2026-09-10&min_coverage=50&min_confidence=25");
    await screen.findByText(/Trend evidence by period and series/);
    expect(lastParams()).toMatchObject({ metric: "occupancy", classroom_id: "1", course_id: "3", activity_context: "EXAMINATION", period: "daily", data_source: "ALL", start_date: "2026-09-01", end_date: "2026-09-10T23:59:59", minimum_coverage: 0.5, confidence_min: 0.25 });
    expect(screen.getByLabelText("Applied filters")).toBeTruthy();
    expect(screen.getByText("Coverage ≥ 50%")).toBeTruthy();
    expect(screen.getByLabelText("10 active filters")).toBeTruthy();
  });

  it("uses EXAMINATION (the backend's canonical value) and no legacy EXAM option", async () => {
    mockApi(); renderPage();
    await screen.findByText(/Trend evidence by period and series/);
    const options = within(screen.getByText("Activity context").closest("label")!).getAllByRole("option").map((option) => (option as HTMLOptionElement).value);
    expect(options).toContain("EXAMINATION");
    expect(options).not.toContain("EXAM");
    expect(options).not.toContain("PRESENTATION");
  });

  it("does not refetch until Apply is pressed, then syncs the URL; Reset clears both", async () => {
    mockApi(); renderPage();
    await screen.findByText(/Trend evidence by period and series/);
    const before = trendCalls().length;
    fireEvent.change(screen.getByLabelText("Minimum coverage (%)"), { target: { value: "40" } });
    fireEvent.change(within(screen.getByText("Data source").closest("label")!).getByRole("combobox"), { target: { value: "DEMO" } });
    expect(trendCalls().length).toBe(before);
    expect(screen.getByText(/Changes are not applied yet/)).toBeTruthy();
    fireEvent.click(screen.getByText("Apply filters"));
    await waitFor(() => expect(trendCalls().length).toBe(before + 1));
    expect(lastParams()).toMatchObject({ minimum_coverage: 0.4, data_source: "DEMO" });
    expect(screen.getByTestId("url").textContent).toContain("min_coverage=40");
    expect(screen.getByTestId("url").textContent).toContain("source=DEMO");
    fireEvent.click(screen.getByText("Reset"));
    await waitFor(() => expect(lastParams().data_source).toBe("REAL"));
    expect(screen.getByTestId("url").textContent).toBe("/analytics-workspace");
  });

  it("blocks Apply for a reversed date range or invalid coverage with associated messages", async () => {
    mockApi(); renderPage();
    await screen.findByText(/Trend evidence by period and series/);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-10" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Minimum coverage (%)"), { target: { value: "150" } });
    expect(screen.getByText("End date must not be before the start date.")).toBeTruthy();
    expect(screen.getByText("Enter a percentage from 0 to 100.")).toBeTruthy();
    expect((screen.getByText("Apply filters") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByLabelText("End date").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByLabelText("End date").getAttribute("aria-describedby")).toBe("end-error");
  });

  it("renders a real table with every required column and honest cell values", async () => {
    mockApi(); renderPage();
    const table = await screen.findByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((header) => header.textContent);
    expect(headers).toEqual(["Period", "Series", "Value", "Availability", "Reason", "Coverage", "Confidence", "Valid observations", "Total observations", "Session count"]);
    expect(within(table).getByText(/Trend evidence by period and series \(3 rows/)).toBeTruthy();
    const rows = within(table).getAllByRole("row").slice(1);
    const cells = (row: HTMLElement) => within(row).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells(rows[0]).slice(0, 2)).toEqual(["Lecture", "0%"]); // genuine zero is shown as 0%, never blank or unavailable
    expect(cells(rows[0])[2]).toBe("Available");
    expect(within(rows[1]).getAllByText("—").length).toBeGreaterThanOrEqual(2); // value and confidence are both unavailable
    expect(cells(rows[1])).toContain("Insufficient evidence");
    expect(cells(rows[1])).toContain("not enough valid observations were available");
    expect(cells(rows[1])[5]).toBe("—"); // confidence unavailable
    expect(table.textContent).not.toMatch(/—%|NaN|undefined/);
  });

  it("gives the table and cells responsive labels for the mobile card layout", async () => {
    mockApi(); renderPage();
    const table = await screen.findByRole("table");
    expect(table.closest(".table-card")).toBeTruthy();
    const firstRow = within(table).getAllByRole("row")[1];
    expect(within(firstRow).getAllByRole("cell").map((cell) => cell.getAttribute("data-th"))).toContain("Coverage");
    expect(table.closest(".table-scroll")).toBeTruthy();
  });

  it("summarises partial evidence and links the chart to its table alternative", async () => {
    mockApi(); renderPage();
    expect(await screen.findByText(/Partial evidence\./)).toBeTruthy();
    expect(screen.getByText(/2 of 3 periods have available evidence/)).toBeTruthy();
    const chart = screen.getByRole("img", { name: /Line chart of Observable participation indicator/ });
    expect(chart.getAttribute("aria-label")).toMatch(/table with every value follows/);
  });

  it("states insufficient evidence when no period is available", async () => {
    mockApi({ ...TRENDS, points: [TRENDS.points[1]] }); renderPage();
    expect(await screen.findByText(/Insufficient evidence\./)).toBeTruthy();
    expect(screen.getByText(/never as zero/)).toBeTruthy();
  });

  it("shows an empty state with a reset action when no sessions match", async () => {
    mockApi({ ...TRENDS, points: [] }); renderPage("/analytics-workspace?activity=BREAK");
    expect(await screen.findByText("No sessions match these filters")).toBeTruthy();
    expect(screen.getByText("Reset filters")).toBeTruthy();
  });

  it("explains hidden periods when the coverage filter removes everything", async () => {
    mockApi({ ...TRENDS, points: [], excluded_by_filters: 3 }); renderPage("/analytics-workspace?min_coverage=90");
    expect(await screen.findByText(/3 period\(s\) were hidden by the minimum coverage or confidence filter/)).toBeTruthy();
  });

  it("shows a loading skeleton, then an error with Retry that reloads", async () => {
    let fail = true;
    get.mockImplementation(async (url: any) => {
      if (String(url).includes("/analytics/trends")) { if (fail) throw { response: { status: 500, data: { error: { code: "INTERNAL_ERROR", message: "Backend exploded", request_id: "req-123" } } } }; return { data: TRENDS } as any; }
      return { data: [] } as any;
    });
    const { container } = renderPage();
    expect(container.querySelector(".skeleton")).toBeTruthy();
    expect(await screen.findByText("Backend exploded")).toBeTruthy();
    expect(screen.getByText(/req-123/)).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByText("Retry"));
    expect(await screen.findByRole("table")).toBeTruthy();
  });

  it("shows an unauthorized state on 403 and an invalid-filters state on 400", async () => {
    mockApi(null, { response: { status: 403, data: { error: { message: "denied" } } } }); renderPage();
    expect(await screen.findByText("You are not authorized to view this analytics scope")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    mockApi(null, { response: { status: 400, data: { error: { code: "INVALID_COVERAGE", message: "minimum_coverage must be between 0.0 and 1.0." } } } }); renderPage();
    expect(await screen.findByText("These filters are not valid")).toBeTruthy();
    expect(screen.getByText("minimum_coverage must be between 0.0 and 1.0.")).toBeTruthy();
  });

  it("ignores a stale response that resolves after a newer request", async () => {
    let resolveFirst: (value: any) => void = () => {};
    let calls = 0;
    get.mockImplementation((url: any) => {
      if (!String(url).includes("/analytics/trends")) return Promise.resolve({ data: [] }) as any;
      calls += 1;
      if (calls === 1) return new Promise((resolve) => { resolveFirst = resolve; }) as any;
      return Promise.resolve({ data: { ...TRENDS, points: [point("2026-W40", "LECTURE", contract({ value: 33 }))] } }) as any;
    });
    renderPage();
    await waitFor(() => expect(calls).toBe(1));
    fireEvent.change(within(screen.getByText("Period").closest("label")!).getByRole("combobox"), { target: { value: "daily" } });
    fireEvent.click(screen.getByText("Apply filters"));
    expect(await screen.findByText("2026-W40")).toBeTruthy();
    resolveFirst({ data: TRENDS }); // the older request finishes last and must be ignored
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText("2026-W36")).toBeNull();
    expect(screen.getByText("2026-W40")).toBeTruthy();
  });

  it("shows the privacy notice and the metric explanation", async () => {
    mockApi(); renderPage();
    await screen.findByRole("table");
    expect(screen.getByText(/does not identify students/)).toBeTruthy();
    expect(screen.getByText(/What does “Observable participation indicator” mean\?/)).toBeTruthy();
  });
});
