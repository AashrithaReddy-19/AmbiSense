// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { api } from "../services/api";
import { SessionsPage } from "./SessionsPage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const get = vi.mocked(api.get);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const ROWS = [
  { id: 1, name: "Lecture A", status: "COMPLETED", source_type: "VIDEO", classroom_id: 1, course_id: null, activity_context: "LECTURE", progress: 100, processed_frames: 10, total_frames: 10, duration: 60, processing_stage: "COMPLETED", analytics_mode: "REAL", is_test: false, created_at: "2026-09-01T00:00:00Z" },
  { id: 2, name: "Lecture B", status: "COMPLETED", source_type: "VIDEO", classroom_id: 1, course_id: null, activity_context: "LECTURE", progress: 100, processed_frames: 10, total_frames: 10, duration: 90, processing_stage: "COMPLETED", analytics_mode: "REAL", is_test: false, created_at: "2026-09-02T00:00:00Z" },
];

function mockApi({ role = "ADMINISTRATOR", listResult = { items: ROWS, page: 1, pages: 1, total: 2 } as any, listError = null as any } = {}) {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u.includes("/v1/auth/me")) return { data: { id: 1, email: "u@test", role, auth_enabled: false } } as any;
    if (u.includes("/v1/sessions")) { if (listError) throw listError; return { data: listResult } as any; }
    if (u.includes("/v1/classrooms")) return { data: [{ id: 1, name: "Room 204" }] } as any;
    if (u.includes("/v1/courses")) return { data: [] } as any;
    return { data: [] } as any;
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <SessionsPage />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("SessionsPage", () => {
  it("shows a loading skeleton before data arrives", async () => {
    let resolve: (v: any) => void = () => {};
    get.mockImplementation((url: any) => {
      if (String(url).includes("/v1/sessions")) return new Promise((r) => { resolve = r; });
      return Promise.resolve({ data: [] });
    });
    const { container } = renderPage();
    expect(container.querySelectorAll(".skeleton-row").length).toBeGreaterThan(0);
    resolve({ data: { items: [], page: 1, pages: 1, total: 0 } });
  });

  it("marks a stale session with a visible Stale badge and explanation, and leaves healthy sessions alone", async () => {
    const stale = { ...ROWS[0], id: 3, name: "Stuck lecture", status: "PROCESSING", processing_stage: "PROCESSING", stale: true, stale_kind: "STALE_VIDEO_JOB", stale_reason: "No worker is processing this video job. Marking it failed lets you retry it." };
    mockApi({ listResult: { items: [{ ...ROWS[0], stale: false }, stale], page: 1, pages: 1, total: 2 } as any });
    renderPage();
    expect(await screen.findByText("Stuck lecture")).toBeTruthy();
    expect(screen.getAllByText("Stale")).toHaveLength(1);
    expect(screen.getByText("Not running: nothing is processing this session")).toBeTruthy();
    expect(screen.getByText("Stale").closest("span")?.getAttribute("title")).toMatch(/No worker is processing/);
  });

  it("shows an empty state with no sessions", async () => {
    mockApi({ listResult: { items: [], page: 1, pages: 1, total: 0 } });
    renderPage();
    expect(await screen.findByText("No sessions found")).toBeTruthy();
  });

  it("shows an error state with retry on failure", async () => {
    mockApi({ listError: { response: { status: 500, data: { detail: "Backend unavailable" } } } });
    renderPage();
    expect(await screen.findByText("Backend unavailable")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("displays real sessions once loaded", async () => {
    mockApi();
    renderPage();
    expect(await screen.findByText("Lecture A")).toBeTruthy();
    expect(screen.getByText("Lecture B")).toBeTruthy();
  });

  it("sends filter parameters to the backend", async () => {
    mockApi();
    renderPage();
    await screen.findByText("Lecture A");
    fireEvent.change(screen.getByLabelText("Status filter"), { target: { value: "COMPLETED" } });
    await waitFor(() => {
      const call = get.mock.calls.find(([url, config]: any) => String(url).includes("/v1/sessions") && config?.params?.status === "COMPLETED");
      expect(call).toBeTruthy();
    });
  });

  it("resets filters", async () => {
    mockApi();
    renderPage();
    await screen.findByText("Lecture A");
    fireEvent.change(screen.getByLabelText("Status filter"), { target: { value: "COMPLETED" } });
    expect(await screen.findByText(/Reset filters/)).toBeTruthy();
    fireEvent.click(screen.getByText(/Reset filters/));
    await waitFor(() => expect(screen.queryByText(/Reset filters/)).toBeNull());
  });

  it("caps selection for comparison at five sessions", async () => {
    const many = Array.from({ length: 6 }, (_, i) => ({ ...ROWS[0], id: i + 1, name: `Session ${i + 1}` }));
    mockApi({ listResult: { items: many, page: 1, pages: 1, total: 6 } });
    renderPage();
    await screen.findByText("Session 1");
    many.forEach((row) => fireEvent.click(screen.getByLabelText(`Select ${row.name} for comparison`)));
    expect(screen.getByText(/Compare selected \(5\)/)).toBeTruthy();
  });

  it("enables compare when 2-5 sessions are selected", async () => {
    mockApi();
    renderPage();
    await screen.findByText("Lecture A");
    fireEvent.click(screen.getByLabelText("Select Lecture A for comparison"));
    fireEvent.click(screen.getByLabelText("Select Lecture B for comparison"));
    const compareButton = screen.getByText(/Compare selected \(2\)/).closest("button") as HTMLButtonElement;
    expect(compareButton.disabled).toBe(false);
  });

  it("hides archive and upload actions for a Viewer", async () => {
    mockApi({ role: "VIEWER" });
    renderPage();
    await screen.findByText("Lecture A");
    expect(screen.queryByText("Upload video")).toBeNull();
    expect(screen.queryByText("Start live")).toBeNull();
    expect(screen.queryByText(/Archive selected/)).toBeNull();
  });

  it("shows archive actions for an Administrator", async () => {
    mockApi({ role: "ADMINISTRATOR" });
    renderPage();
    await screen.findByText("Lecture A");
    expect(screen.getAllByText("Archive").length).toBeGreaterThan(0);
  });

  it("navigates to the session detail page", async () => {
    mockApi();
    renderPage();
    const link = await screen.findByText("Lecture A");
    expect(link.getAttribute("href")).toBe("/sessions/1");
  });
});

describe("SessionsPage date-range and coverage filters (Phase 3C)", () => {
  function renderAt(path: string) {
    return render(<MemoryRouter initialEntries={[path]}><AuthProvider><SessionsPage /></AuthProvider></MemoryRouter>);
  }
  const listCalls = () => get.mock.calls.filter(([url]) => String(url).includes("/v1/sessions"));
  const lastParams = () => (listCalls().at(-1)?.[1] as any).params;

  it("sends start date, end date (inclusive of the whole day) and minimum coverage (as a fraction) to the server", async () => {
    mockApi(); renderPage();
    await screen.findByText("Lecture A");
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-01" } });
    await waitFor(() => expect(lastParams().start_date).toBe("2026-09-01"));
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-30" } });
    await waitFor(() => expect(lastParams().end_date).toBe("2026-09-30T23:59:59"));
    fireEvent.change(screen.getByLabelText("Minimum coverage (%)"), { target: { value: "50" } });
    await waitFor(() => expect(lastParams().minimum_coverage).toBe(0.5));
    expect(lastParams()).toMatchObject({ start_date: "2026-09-01", end_date: "2026-09-30T23:59:59", minimum_coverage: 0.5, page: 1 });
  });

  it("accepts a genuine 0% minimum coverage and sends it", async () => {
    mockApi(); renderPage();
    await screen.findByText("Lecture A");
    fireEvent.change(screen.getByLabelText("Minimum coverage (%)"), { target: { value: "0" } });
    await waitFor(() => expect(lastParams().minimum_coverage).toBe(0));
  });

  it("initializes the new filters from the URL and counts them as active", async () => {
    mockApi(); renderAt("/sessions?start_date=2026-09-01&end_date=2026-09-10&minimum_coverage=25&page=2");
    await screen.findByText("Lecture A");
    expect(lastParams()).toMatchObject({ start_date: "2026-09-01", end_date: "2026-09-10T23:59:59", minimum_coverage: 0.25, page: 2 });
    expect((screen.getByLabelText("Start date") as HTMLInputElement).value).toBe("2026-09-01");
    expect((screen.getByLabelText("Minimum coverage (%)") as HTMLInputElement).value).toBe("25");
    expect(screen.getByText("Reset filters (3)")).toBeTruthy();
  });

  it("keeps the filters while paginating", async () => {
    mockApi({ listResult: { items: ROWS, page: 1, pages: 3, total: 50 } });
    renderAt("/sessions?minimum_coverage=40&start_date=2026-09-01");
    await screen.findByText("Lecture A");
    fireEvent.click(screen.getByText("Next"));
    await waitFor(() => expect(lastParams()).toMatchObject({ page: 2, minimum_coverage: 0.4, start_date: "2026-09-01" }));
  });

  it("explains a reversed date range and does not send the invalid request", async () => {
    mockApi(); renderPage();
    await screen.findByText("Lecture A");
    const before = listCalls().length;
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-10" } });
    await waitFor(() => expect(listCalls().length).toBe(before + 1));
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-01" } });
    expect(await screen.findByText("End date must not be before the start date.")).toBeTruthy();
    expect(screen.getByLabelText("End date").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Fix the highlighted filters to update the results.")).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(listCalls().length).toBe(before + 1); // no request while invalid
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-20" } });
    await waitFor(() => expect(listCalls().length).toBe(before + 2));
    expect(screen.queryByText("End date must not be before the start date.")).toBeNull();
  });

  it.each(["150", "-5"])("rejects an out-of-range minimum coverage (%s) without calling the server", async (value) => {
    mockApi(); renderPage();
    await screen.findByText("Lecture A");
    const before = listCalls().length;
    fireEvent.change(screen.getByLabelText("Minimum coverage (%)"), { target: { value } });
    expect(await screen.findByText("Enter a percentage from 0 to 100.")).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(listCalls().length).toBe(before);
  });

  it("resets the date and coverage filters together with the rest", async () => {
    mockApi(); renderAt("/sessions?start_date=2026-09-01&minimum_coverage=25");
    await screen.findByText("Lecture A");
    fireEvent.click(screen.getByText("Reset filters (2)"));
    await waitFor(() => expect(lastParams().start_date).toBeUndefined());
    expect(lastParams().minimum_coverage).toBeUndefined();
    expect((screen.getByLabelText("Start date") as HTMLInputElement).value).toBe("");
    expect(screen.queryByText(/Reset filters \(/)).toBeNull();
  });

  it("describes what coverage means", async () => {
    mockApi(); renderPage();
    await screen.findByText("Lecture A");
    expect(screen.getByText(/at least one person was detected/)).toBeTruthy();
  });
});
