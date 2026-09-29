// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/Toast";
import { api } from "../services/api";
import { downloadFile } from "../services/download";
import { ReportsPage, progressText } from "./ReportsPage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock("../services/download", async (importOriginal) => ({ ...(await importOriginal<typeof import("../services/download")>()), downloadFile: vi.fn() }));
const get = vi.mocked(api.get), post = vi.mocked(api.post), download = vi.mocked(downloadFile);
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers(); });

const summary = (frame: any = { value: 82, available: true, reason: null, coverage: 1, confidence: 0.9, valid_observations: 5, total_observations: 5 }) => ({ frame_quality: frame, observable_participation: { value: 70, available: true, reason: null, coverage: 0.85, confidence: 0.8, valid_observations: 8, total_observations: 10 } });
const ROW = (overrides: Record<string, unknown> = {}) => ({ session_id: 41, name: "Physics lecture", source_filename: "physics.mp4", source_type: "VIDEO", status: "COMPLETED", stage: "COMPLETED", progress: 100, created_at: "2026-09-20T10:00:00", analytics_mode: "REAL", is_test: false, error: null, failure_code: null, job_id: "job41", available_formats: ["csv", "metrics", "pdf"], report_ready: true, classroom_id: 1, course_id: null, activity_context: "LECTURE", duration: 600, metric_results: summary(), ...overrides });
const PAGE = (items: any[], extra: Record<string, unknown> = {}) => ({ items, page: 1, pages: 1, total: items.length, page_size: 20, ...extra });

function mockApi(reports: any = PAGE([ROW()]), overrides: Record<string, any> = {}) {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (overrides[u] !== undefined) { const value = overrides[u]; if (value instanceof Error || value?.response) throw value; return value as any; }
    if (u.includes("/v1/reports")) { if (reports?.response) throw reports; return { data: reports } as any; }
    if (u.includes("/v1/classrooms")) return { data: [{ id: 1, name: "Room 204" }] } as any;
    if (u.includes("/v1/courses")) return { data: [{ id: 3, code: "CS101", name: "Intro" }] } as any;
    if (u.includes("/analytics")) return { data: { metric_results: { occupancy: { value: 0, available: true, reason: null, coverage: 1, confidence: 0.9, valid_observations: 1, total_observations: 1 }, ...summary() } } } as any;
    if (u.includes("/quality")) return { data: { status: "GOOD", overall_quality: 82, warnings: ["Video appears blurred; landmark metrics may be unreliable."] } } as any;
    if (u.includes("/artifacts")) return { data: { artifacts: [{ kind: "report_pdf", label: "Report (PDF)", filename: "session_41.pdf", size_bytes: 2048, media_type: "application/pdf", url: "/api/sessions/41/report?format=pdf" }, { kind: "annotated_video", label: "Annotated video", filename: "annotated_41.mp4", size_bytes: 5242880, media_type: "video/mp4", url: "/api/sessions/41/video?annotated=true" }] } } as any;
    return { data: [] } as any;
  });
}
const renderPage = (path = "/reports") => render(<MemoryRouter initialEntries={[path]}><ToastProvider><ReportsPage /></ToastProvider></MemoryRouter>);
const reportCalls = () => get.mock.calls.filter(([url]) => String(url).includes("/v1/reports"));
const lastParams = () => (reportCalls().at(-1)?.[1] as any).params;

describe("progressText", () => {
  it("never produces a malformed percentage", () => {
    expect(progressText(45.5)).toBe("46%");
    expect(progressText(0)).toBe("0%");
    expect(progressText(140)).toBe("100%");
    for (const bad of [undefined, null, Number.NaN, Number.POSITIVE_INFINITY]) expect(progressText(bad as any)).toBeNull();
  });
});

describe("ReportsPage", () => {
  it("loads newest first with the source filename, status, quality, formats and correct IDs", async () => {
    mockApi(PAGE([ROW(), ROW({ session_id: 42, name: "Live lab", source_type: "LIVE", source_filename: null, created_at: "2026-09-19T10:00:00" })]));
    renderPage();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Reports, newest first")).toBeTruthy();
    const rows = within(table).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText(/physics\.mp4/)).toBeTruthy();
    expect(within(rows[1]).getByText(/Live session/)).toBeTruthy();
    expect(within(rows[0]).getByText("COMPLETED")).toBeTruthy();
    expect(within(rows[0]).getByText(/82%/)).toBeTruthy();
    expect(within(rows[0]).getByText("Coverage 85%")).toBeTruthy();
    expect(within(rows[0]).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["CSV", "Metrics CSV", "PDF"]);
    expect(within(rows[0]).getByRole("link", { name: "Physics lecture" }).getAttribute("href")).toBe("/sessions/41");
    expect(within(rows[1]).getByRole("link", { name: "Live lab" }).getAttribute("href")).toBe("/sessions/42");
    expect(table.textContent).not.toMatch(/—%|NaN%|undefined/);
  });

  it("sends every filter to the backend and defaults to real data", async () => {
    mockApi(); renderPage();
    await screen.findByRole("table");
    expect(lastParams()).toMatchObject({ data_source: "REAL", page: 1, page_size: 20 });
    cleanup(); vi.resetAllMocks(); mockApi();
    renderPage("/reports?q=physics&status=FAILED&source_type=LIVE&classroom=1&course=3&activity=EXAMINATION&source=ALL&format=pdf&start=2026-09-01&end=2026-09-30");
    await screen.findByRole("table");
    expect(lastParams()).toMatchObject({ q: "physics", status: "FAILED", source_type: "LIVE", classroom_id: "1", course_id: "3", activity_context: "EXAMINATION", data_source: "ALL", format: "pdf", start_date: "2026-09-01", end_date: "2026-09-30T23:59:59" });
  });

  it("applies filters only on Apply and resets to the first page", async () => {
    mockApi(PAGE([ROW()], { pages: 3, total: 50 }));
    renderPage("/reports?page=2");
    await screen.findByRole("table");
    expect(lastParams().page).toBe(2);
    fireEvent.change(screen.getByPlaceholderText("Session or file name"), { target: { value: "chem" } });
    expect(reportCalls().length).toBe(1);
    fireEvent.click(screen.getByText("Apply filters"));
    await waitFor(() => expect(lastParams()).toMatchObject({ q: "chem", page: 1 }));
  });

  it("preserves filters while paginating", async () => {
    mockApi(PAGE([ROW()], { pages: 3, total: 50 }));
    renderPage("/reports?status=COMPLETED");
    await screen.findByRole("table");
    fireEvent.click(screen.getByLabelText("Next page"));
    await waitFor(() => expect(lastParams()).toMatchObject({ status: "COMPLETED", page: 2 }));
    expect(screen.getByText(/Page 1 of 3 · 50 reports|Page 2 of 3/)).toBeTruthy();
  });

  it("validates the date range before applying", async () => {
    mockApi(); renderPage();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-10" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-01" } });
    expect(screen.getByText("End date must not be before the start date.")).toBeTruthy();
    expect((screen.getByText("Apply filters") as HTMLButtonElement).disabled).toBe(true);
  });

  it("disables actions for formats that do not exist or a session that is not completed", async () => {
    mockApi(PAGE([ROW({ available_formats: ["csv"] }), ROW({ session_id: 43, name: "Still running", status: "PROCESSING", progress: 45.5, available_formats: [], report_ready: false })]));
    renderPage();
    const table = await screen.findByRole("table");
    const [done, running] = within(table).getAllByRole("row").slice(1);
    expect((within(done).getByLabelText("Download PDF for Physics lecture") as HTMLButtonElement).disabled).toBe(true);
    expect((within(done).getByLabelText("Download CSV for Physics lecture") as HTMLButtonElement).disabled).toBe(false);
    expect((within(running).getByLabelText("Download PDF for Still running") as HTMLButtonElement).disabled).toBe(true);
    expect(within(running).getByText(/46%/)).toBeTruthy();
    expect(within(running).queryByText("Retry")).toBeNull();
  });

  it("downloads with the session id (not the row position), reports success, and ignores a duplicate click while in flight", async () => {
    mockApi(PAGE([ROW({ session_id: 907 })]));
    let finish: (value: string) => void = () => {};
    download.mockImplementation(() => new Promise<string>((resolve) => { finish = resolve; }));
    renderPage();
    const button = await screen.findByLabelText("Download PDF for Physics lecture");
    fireEvent.click(button); fireEvent.click(button);
    expect(download).toHaveBeenCalledTimes(1);
    expect(download).toHaveBeenCalledWith("/sessions/907/report?format=pdf", "session_907.pdf");
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { finish("session_907.pdf"); });
    expect(await screen.findByText("PDF downloaded.")).toBeTruthy();
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows a toast with the server's message when a download fails", async () => {
    mockApi(); download.mockRejectedValue({ response: { status: 409, data: { error: { message: "Report is unavailable until processing completes" } } } });
    renderPage();
    fireEvent.click(await screen.findByLabelText("Download CSV for Physics lecture"));
    expect(await screen.findByText("Report is unavailable until processing completes")).toBeTruthy();
  });

  it("offers a safe retry for a failed job and reloads afterwards", async () => {
    mockApi(PAGE([ROW({ status: "FAILED", available_formats: [], report_ready: false, error: "Decoder crashed (reference abc)", failure_code: "VIDEO_DECODING_FAILED", job_id: "job-failed" })]));
    post.mockResolvedValue({ data: { status: "QUEUED" } } as any);
    renderPage();
    expect(await screen.findByText(/Decoder crashed/)).toBeTruthy();
    fireEvent.click(screen.getByText("Retry"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/jobs/job-failed/retry"));
    expect(await screen.findByText("Processing was queued again.")).toBeTruthy();
    await waitFor(() => expect(reportCalls().length).toBeGreaterThan(1));
  });

  it("opens a details drawer built from API data with metrics, quality, methodology, privacy and downloads", async () => {
    mockApi(); renderPage();
    fireEvent.click(await screen.findByText("Details"));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Report details · Physics lecture")).toBeTruthy();
    expect(await within(drawer).findByText("Metrics")).toBeTruthy();
    expect(within(drawer).getByText(/^0 people/)).toBeTruthy(); // genuine zero occupancy
    expect(within(drawer).getByText(/Video appears blurred/)).toBeTruthy();
    expect(within(drawer).getByText("Methodology")).toBeTruthy();
    expect(within(drawer).getByText(/does not identify students/)).toBeTruthy();
    expect(within(drawer).getByText(/Not validated on real classroom footage/)).toBeTruthy();
    expect(within(drawer).getByText("Limitations")).toBeTruthy();
    expect(within(drawer).getByText("Report (PDF)")).toBeTruthy();
    expect(within(drawer).getByText("Annotated video")).toBeTruthy();
    expect(within(drawer).getByRole("link", { name: "Open full session" }).getAttribute("href")).toBe("/sessions/41");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the drawer useful when part of the detail data fails to load", async () => {
    mockApi(PAGE([ROW()]), { "/v1/sessions/41/quality": { response: { status: 500, data: {} } } });
    renderPage();
    fireEvent.click(await screen.findByText("Details"));
    expect(await screen.findByText(/Some details could not be loaded: evidence quality/)).toBeTruthy();
    expect(screen.getByText("Report (PDF)")).toBeTruthy();
  });

  it("shows loading, empty, error with retry, and unauthorized states", async () => {
    let resolve: (value: any) => void = () => {};
    get.mockImplementation((url: any) => (String(url).includes("/v1/reports") ? new Promise((r) => { resolve = r; }) : Promise.resolve({ data: [] })) as any);
    const { container } = renderPage();
    expect(container.querySelector(".skeleton-row")).toBeTruthy();
    await act(async () => { resolve({ data: PAGE([]) }); });
    expect(await screen.findByText("No reports match these filters")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    mockApi({ response: { status: 500, data: { error: { message: "Reports exploded", request_id: "req-9" } } } });
    renderPage();
    expect(await screen.findByText("Reports exploded")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    mockApi({ response: { status: 403, data: { error: { message: "denied" } } } });
    renderPage();
    expect(await screen.findByText("You are not authorized to view these reports")).toBeTruthy();
  });

  it("polls only while something is processing and stops afterwards", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    mockApi(PAGE([ROW({ status: "PROCESSING", progress: 10, available_formats: [] })]));
    renderPage();
    await screen.findByRole("table");
    const initial = reportCalls().length;
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(reportCalls().length).toBe(initial + 1);
    mockApi(PAGE([ROW()]));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    await screen.findByText("COMPLETED");
    const settled = reportCalls().length;
    await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
    expect(reportCalls().length).toBe(settled); // polling stopped once nothing is active
  });
});
