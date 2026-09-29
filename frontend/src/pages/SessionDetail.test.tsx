// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { BreadcrumbProvider, BreadcrumbTrail } from "../components/Breadcrumbs";
import { ToastProvider } from "../components/Toast";
import { api } from "../services/api";
import { downloadFile } from "../services/download";
import { SessionDetail } from "./SessionDetail";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock("../services/download", async (importOriginal) => ({ ...(await importOriginal<typeof import("../services/download")>()), downloadFile: vi.fn() }));
class FakeResizeObserver { observe() {} unobserve() {} disconnect() {} }
vi.stubGlobal("ResizeObserver", FakeResizeObserver);
const get = vi.mocked(api.get), post = vi.mocked(api.post), del = vi.mocked(api.delete), download = vi.mocked(downloadFile);
// Reset the one piece of global state the breadcrumb writes, so no test can observe another test's title.
beforeEach(() => { document.title = ""; });
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const SESSION = { id: 203, name: "Real lecture recording", status: "COMPLETED", source_type: "VIDEO", source_filename: "lecture.mp4", classroom_id: 1, course_id: null, activity_context: "LECTURE", analytics_mode: "REAL", annotated_video_path: "/x.mp4", duration: 1800, started_at: "2026-09-01T09:00:00", created_at: "2026-09-01T08:59:00", processed_frames: 90, total_frames: 90, error: null };
const SUMMARY = {
  session_id: 203, status: "COMPLETED", snapshots: 4, peak_engagement: 80, lowest_engagement: 40, average_students: 12, minimum_students: 8, peak_raised_hands: 3, total_yawns: 2,
  metric_results: {
    occupancy: { value: 0, available: true, reason: null, coverage: 1, confidence: 0.9, valid_observations: 1, total_observations: 1 },
    peak_occupancy: { value: null, available: false, reason: "legacy_data_without_evidence", coverage: null, confidence: null, valid_observations: 0, total_observations: 0 },
    visual_orientation: { value: null, available: false, reason: "insufficient_valid_observations", coverage: 0.1, confidence: null, valid_observations: 1, total_observations: 10 },
    unoccupied_capacity: {}, observable_participation: {}, prolonged_eye_closure: {}, possible_fatigue: {}, yawning: {}, raised_hands: {}, frame_quality: {},
  },
};
const EVENTS = [{ id: 1, timestamp: 12.5, type: "HAND_RAISED", severity: "INFO", message: "Raised-hand observation", review_state: "UNREVIEWED", reviewer_note: null, included_in_report: true }];
const TIMELINE = [{ timestamp: 0, student_count: 5, engagement: 60, attention: 70, fatigue: 10 }, { timestamp: 5, student_count: 6, engagement: 65, attention: 72, fatigue: 12 }];
const QUALITY = { status: "GOOD", overall_quality: 76.5, warnings: ["Video appears blurred; landmark metrics may be unreliable."], timeline: [{ timestamp: 0, brightness: 130, blur: 30 }, { timestamp: 5, brightness: 140, blur: 40 }], frame_quality: { value: 76.5, available: true, reason: null, coverage: 1, confidence: null, valid_observations: 2, total_observations: 2 } };
const ARTIFACTS = [{ kind: "report_pdf", label: "Report (PDF)", filename: "session_203.pdf", size_bytes: 2048, media_type: "application/pdf", url: "/api/sessions/203/report?format=pdf" }, { kind: "report_csv", label: "Report (CSV)", filename: "session_203.csv", size_bytes: 512, media_type: "text/csv", url: "/api/sessions/203/report?format=csv" }, { kind: "annotated_video", label: "Annotated video", filename: "annotated_203.mp4", size_bytes: 5242880, media_type: "video/mp4", url: "/api/sessions/203/video?annotated=true" }];
const REGIONS_OK = { status: "CALIBRATED", layout_id: 4, layout_version: 3, regions: [{ region_id: "r1", name: "Front row", observation_count: 12, estimated_unique_tracks: 5, raised_hand_observations: 2, visual_coverage: 80 }] };

type Options = { role?: string; session?: any; summary?: any; timeline?: any[]; events?: any[]; quality?: any; regions?: any; artifacts?: any[] | Error; notes?: any[]; error?: any };
function mockApi(options: Options = {}) {
  const { role = "ADMINISTRATOR", session = SESSION, summary = SUMMARY, timeline = TIMELINE, events = EVENTS, quality = QUALITY, regions = { status: "UNCALIBRATED", regions: [] }, artifacts = ARTIFACTS, notes = [], error = null } = options;
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u.includes("/v1/auth/me")) return { data: { id: 1, email: "u@test", role, auth_enabled: true } } as any;
    if (error && u === `/sessions/${session.id}`) throw error;
    if (u.match(/^\/sessions\/\d+$/)) return { data: session } as any;
    if (u.includes("/analytics")) return { data: summary } as any;
    if (u.includes("/timeline")) return { data: timeline } as any;
    if (u.endsWith("/events")) return { data: events } as any;
    if (u.includes("/quality")) return { data: quality } as any;
    if (u.includes("/regions")) return { data: regions } as any;
    if (u.includes("/artifacts")) { if (artifacts instanceof Error) throw artifacts; return { data: { artifacts } } as any; }
    if (u.includes("/audio/capabilities")) return { data: { status: "DISABLED", reason: "Audio analytics is disabled.", audio_processing_enabled: false, transcription: { configured: false }, diarization: { configured: false } } } as any;
    if (u.includes("/v1/notes")) return { data: notes } as any;
    if (u.includes("/v1/classrooms")) return { data: [{ id: 1, name: "Room 204" }] } as any;
    if (u.includes("/v1/courses")) return { data: [] } as any;
    if (u.endsWith("/audio")) return { data: { status: "NOT_PROCESSED", quality_status: "UNAVAILABLE", quality: {}, coverage: {}, limitations: ["Audio intelligence has not run for this session."] } } as any;
    if (u.endsWith("/transcript")) return { data: { status: "UNAVAILABLE", segments: [], limitations: [] } } as any;
    if (u.endsWith("/discourse")) return { data: { status: "NOT_PROCESSED", metrics: {}, limitations: [] } } as any;
    if (u.endsWith("/content")) return { data: { status: "UNAVAILABLE", chapters: [], items: [], limitations: [] } } as any;
    if (u.endsWith("/evidence-graph")) return { data: { status: "NOT_PROCESSED", nodes: [], edges: [], limitations: [] } } as any;
    return { data: [] } as any;
  });
}
function Where() { const location = useLocation(); return <output data-testid="url">{location.pathname}{location.search}</output>; }
function renderPage(path = "/sessions/203") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider><ToastProvider><BreadcrumbProvider>
        <BreadcrumbTrail />
        <Routes><Route path="/sessions/:id" element={<SessionDetail />} /><Route path="/sessions" element={<div>Sessions list</div>} /></Routes>
        <Where />
      </BreadcrumbProvider></ToastProvider></AuthProvider>
    </MemoryRouter>,
  );
}
const ready = () => screen.findByRole("heading", { name: "Real lecture recording" });
const tab = (name: RegExp) => screen.getByRole("tab", { name });
const tabNames = () => screen.getAllByRole("tab").map((node) => node.textContent?.replace(/\d+$/, ""));
const callsTo = (fragment: string) => get.mock.calls.filter(([url]) => String(url).includes(fragment)).length;

describe("SessionDetail basics", () => {
  it("shows a loading state before data arrives", () => {
    get.mockImplementation(() => new Promise(() => {}));
    renderPage();
    expect(screen.getByText(/Loading session evidence/)).toBeTruthy();
  });

  it("shows an error state with retry on failure", async () => {
    mockApi({ error: { response: { status: 404 } } });
    renderPage();
    expect(await screen.findByText("This session was not found.")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("shows an unauthorized state on 403", async () => {
    mockApi({ error: { response: { status: 403, data: { error: { message: "denied" } } } } });
    renderPage();
    expect(await screen.findByText("You are not authorized to view this session.")).toBeTruthy();
  });

  it("sets the document title and breadcrumb to the real session name", async () => {
    mockApi(); renderPage();
    await ready();
    // The title is written by an effect chain that runs after the heading first paints, so wait for it.
    await waitFor(() => expect(document.title).toContain("Real lecture recording"));
    expect(await screen.findByText("Real lecture recording", { selector: ".current" })).toBeTruthy();
  });

  it("keeps the breadcrumb and document title while switching tabs", async () => {
    mockApi(); renderPage();
    await ready();
    fireEvent.click(tab(/^Notes/));
    await waitFor(() => expect(screen.getByTestId("url").textContent).toContain("tab=notes"));
    expect(document.title).toContain("Real lecture recording");
    expect(screen.getByText("Real lecture recording", { selector: ".current" })).toBeTruthy();
  });

  it("explains a stale session and points administrators to the recovery workflow", async () => {
    mockApi({ session: { ...SESSION, status: "PROCESSING", stale: true, stale_kind: "STALE_VIDEO_JOB", stale_reason: "No worker is processing this video job. Marking it failed lets you retry it." } as any }); renderPage();
    await ready();
    expect(screen.getByText("This session looks stale.")).toBeTruthy();
    expect(screen.getByText(/cannot survive a server restart/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Review stale sessions in Settings/ }).getAttribute("href")).toBe("/settings");
  });

  it("shows no stale banner for a healthy session", async () => {
    mockApi({ session: { ...SESSION, stale: false } as any }); renderPage();
    await ready();
    expect(screen.queryByText("This session looks stale.")).toBeNull();
  });

  it("displays a genuine zero occupancy value, not Unavailable, and an unavailable reason for other metrics", async () => {
    mockApi(); renderPage();
    await ready();
    expect(screen.getByText(/^0 people/)).toBeTruthy();
    expect(screen.getByText(/Unavailable — this session predates evidence tracking/)).toBeTruthy();
    expect(screen.getByText(/Insufficient evidence — 1 of 10 observations were valid/)).toBeTruthy();
  });

  it("shows the three privacy statements and the validation status on the overview", async () => {
    mockApi(); renderPage();
    await ready();
    expect(screen.getByText(/does not identify students/)).toBeTruthy();
    expect(screen.getByText("Occupancy is an estimate and is not verified attendance.")).toBeTruthy();
    expect(screen.getAllByText(/sole basis for grading, discipline, attendance/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Not validated on real classroom footage/)).toBeTruthy();
  });

  it("offers report downloads only when completed, and a status timeline only when not terminal", async () => {
    mockApi(); renderPage();
    await ready();
    expect(screen.getByText("PDF")).toBeTruthy();
    expect(screen.getByText("CSV")).toBeTruthy();
    expect(screen.queryByLabelText("Processing status")).toBeNull();
    cleanup(); vi.resetAllMocks();
    mockApi({ session: { ...SESSION, status: "PROCESSING" } }); renderPage();
    await ready();
    expect(screen.queryByText("PDF")).toBeNull();
    expect(screen.getByLabelText("Processing status")).toBeTruthy();
  });

  it("downloads through the authenticated client and ignores a duplicate click while in flight", async () => {
    mockApi();
    let finish: (value: string) => void = () => {};
    download.mockImplementation(() => new Promise<string>((resolve) => { finish = resolve; }));
    renderPage();
    await ready();
    const pdf = screen.getByText("PDF").closest("button") as HTMLButtonElement;
    fireEvent.click(pdf); fireEvent.click(pdf);
    expect(download).toHaveBeenCalledTimes(1);
    expect(download).toHaveBeenCalledWith("/sessions/203/report?format=pdf", "session_203.pdf");
    await act(async () => { finish("session_203.pdf"); });
    expect(pdf.disabled).toBe(false);
  });
});

describe("SessionDetail tabs", () => {
  it("shows every meaningful tab for a completed session with evidence", async () => {
    mockApi({ regions: REGIONS_OK }); renderPage();
    await ready();
    expect(tabNames()).toEqual(["Overview", "Timeline", "Quality & Evidence", "Regions", "Artifacts", "Notes"]);
    expect(tab(/^Overview/).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tablist", { name: "Session sections" })).toBeTruthy();
  });

  it("hides tabs that would be empty", async () => {
    mockApi({ session: { ...SESSION, status: "PROCESSING", classroom_id: null, annotated_video_path: null }, summary: { ...SUMMARY, snapshots: 0 }, timeline: [], events: [], quality: { status: "UNAVAILABLE", warnings: [], timeline: [] }, artifacts: [] });
    renderPage();
    await ready();
    expect(tabNames()).toEqual(["Overview", "Notes"]);
  });

  it("only requests the annotated video when the session has one (no 404 for a missing file)", async () => {
    mockApi({ session: { ...SESSION, annotated_video_path: null } }); const without = renderPage();
    await ready();
    expect(without.container.querySelector("video")).toBeNull();
    expect(screen.getByText(/Annotated video becomes available/)).toBeTruthy();
    without.unmount();
    mockApi({}); const withVideo = renderPage();
    await ready();
    expect(withVideo.container.querySelector("video")?.getAttribute("src")).toBe("/api/sessions/203/video?annotated=true");
  });

  it("explains an unplayable annotated video and offers the file as a download instead of a dead player", async () => {
    mockApi({}); const { container } = renderPage();
    await ready();
    expect(screen.queryByText(/cannot play the annotated video/)).toBeNull();
    fireEvent.error(container.querySelector("video") as HTMLVideoElement);
    expect(await screen.findByText(/cannot play the annotated video/)).toBeTruthy();
    const link = screen.getByRole("link", { name: "Download annotated video" });
    expect(link.getAttribute("href")).toBe("/api/sessions/203/video?annotated=true");
    expect(link.hasAttribute("download")).toBe(true);
  });

  it("supports arrow-key navigation, Home/End, and keeps ?tab= in sync", async () => {
    mockApi({ regions: REGIONS_OK }); renderPage();
    await ready();
    fireEvent.keyDown(tab(/^Overview/), { key: "ArrowRight" });
    expect(tab(/^Timeline/).getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tab(/^Timeline/));
    expect(screen.getByTestId("url").textContent).toBe("/sessions/203?tab=timeline");
    fireEvent.keyDown(tab(/^Timeline/), { key: "End" });
    expect(tab(/^Notes/).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab(/^Notes/), { key: "Home" });
    expect(screen.getByTestId("url").textContent).toBe("/sessions/203"); // Overview is the default, so no parameter is needed
    fireEvent.keyDown(tab(/^Overview/), { key: "ArrowLeft" });
    expect(tab(/^Notes/).getAttribute("aria-selected")).toBe("true");
  });

  it("opens the tab named in the URL, and falls back to Overview for an unknown or unavailable tab", async () => {
    mockApi(); renderPage("/sessions/203?tab=notes");
    await ready();
    expect(tab(/^Notes/).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("No notes yet")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    mockApi({ session: { ...SESSION, classroom_id: null } }); renderPage("/sessions/203?tab=regions"); // no classroom, so no Regions tab
    await ready();
    expect(tab(/^Overview/).getAttribute("aria-selected")).toBe("true");
    cleanup(); vi.resetAllMocks();
    mockApi(); renderPage("/sessions/203?tab=bogus");
    await ready();
    expect(tab(/^Overview/).getAttribute("aria-selected")).toBe("true");
  });

  it("never fetches the same data twice when switching between tabs", async () => {
    mockApi({ regions: REGIONS_OK }); renderPage();
    await ready();
    for (const name of [/^Timeline/, /^Quality & Evidence/, /^Notes/, /^Overview/, /^Timeline/, /^Quality & Evidence/, /^Notes/]) fireEvent.click(tab(name));
    await screen.findByText("No notes yet");
    for (const fragment of ["/analytics", "/timeline", "/events", "/quality", "/regions", "/artifacts", "/audio/capabilities", "/v1/notes"]) expect(callsTo(fragment), fragment).toBe(1);
    expect(callsTo("/transcript")).toBe(1);
  });

  it("uses proper tabpanel semantics and keeps visited panels mounted but hidden", async () => {
    mockApi(); renderPage();
    await ready();
    fireEvent.click(tab(/^Timeline/));
    const timelinePanel = screen.getByRole("tabpanel");
    expect(timelinePanel.getAttribute("aria-labelledby")).toBe(tab(/^Timeline/).id);
    expect(document.getElementById("session-tab-panel-overview")?.hasAttribute("hidden")).toBe(true);
  });
});

describe("Timeline tab", () => {
  it("lists events with timestamp, severity and review state, and offers a table alternative to the chart", async () => {
    mockApi({ role: "REVIEWER" }); renderPage("/sessions/203?tab=timeline");
    await ready();
    const events = (await screen.findByText("Events (1)")).closest("section")!;
    expect(within(events).getByText("12.5s")).toBeTruthy();
    expect(within(events).getByText("HAND_RAISED")).toBeTruthy();
    expect(screen.getByText("Show timeline as a table")).toBeTruthy();
    expect(screen.getByRole("img", { name: /same values are listed in the table below/ })).toBeTruthy();
    expect(screen.getByText("Anonymous occupancy")).toBeTruthy();
  });

  it("gives reviewers review controls and viewers a read-only list", async () => {
    mockApi({ role: "REVIEWER" }); renderPage("/sessions/203?tab=timeline");
    await ready();
    await waitFor(() => expect(screen.getByLabelText("Review state")).toBeTruthy());
    expect(screen.getByText("Save review")).toBeTruthy();
    expect(within(screen.getByRole("tabpanel")).queryByText(/Your role can view events but not review them/)).toBeNull();
    cleanup(); vi.resetAllMocks();
    mockApi({ role: "VIEWER" }); renderPage("/sessions/203?tab=timeline");
    await ready();
    expect(await screen.findByText(/Your role can view events but not review them/)).toBeTruthy();
    expect(screen.queryByLabelText("Review state")).toBeNull();
    expect(screen.queryByText("Save review")).toBeNull();
    expect(within(screen.getByRole("tabpanel")).getByText("Raised-hand observation")).toBeTruthy();
  });
});

describe("Quality & Evidence tab", () => {
  it("shows a per-metric evidence table with availability, reason, coverage, confidence and observation counts", async () => {
    mockApi(); renderPage("/sessions/203?tab=evidence");
    await ready();
    const table = await screen.findByRole("table", { name: "Evidence by metric" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Metric", "Value", "Availability", "Reason", "Coverage", "Confidence", "Valid", "Total"]);
    const zero = within(table).getByText("Anonymous occupancy estimate").closest("tr")!;
    expect(within(zero).getByText("Available")).toBeTruthy();
    expect(within(zero).getByText(/^0 people/)).toBeTruthy();
    const insufficient = within(table).getByText("Visual-orientation estimate").closest("tr")!;
    expect(within(insufficient).getByText("Insufficient evidence")).toBeTruthy();
    expect(within(insufficient).getByText("not enough valid observations were available")).toBeTruthy();
    expect(table.textContent).not.toMatch(/—%|NaN/);
  });

  it("summarises frame quality, lighting and sharpness from stored assessments", async () => {
    mockApi(); renderPage("/sessions/203?tab=evidence");
    await ready();
    expect(await screen.findByText("76.5/100")).toBeTruthy();
    expect(screen.getByText("Adequate", { selector: "b" }) ).toBeTruthy();
    expect(screen.getByText(/Mean brightness 135\/255/)).toBeTruthy();
    expect(screen.getAllByText(/Video appears blurred/).length).toBeGreaterThan(0);
  });

  it("reports optional audio as Disabled when the capability is off (never operational)", async () => {
    mockApi(); renderPage("/sessions/203?tab=evidence");
    await ready();
    expect(await screen.findByText("Disabled")).toBeTruthy();
    expect(screen.getByText(/Audio analytics is disabled/)).toBeTruthy();
  });
});

describe("Regions tab", () => {
  it("shows the real layout version and per-region evidence when calibrated", async () => {
    mockApi({ regions: REGIONS_OK }); renderPage("/sessions/203?tab=regions");
    await ready();
    expect(await screen.findByText(/Calibrated layout #4 · version 3/)).toBeTruthy();
    const row = screen.getByText("Front row").closest("tr")!;
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["5", "12", "2", "80%"]);
  });

  it("shows a clear empty state (no invented heat map) when uncalibrated", async () => {
    mockApi(); renderPage("/sessions/203?tab=regions");
    await ready();
    expect(await screen.findByText("No calibrated region evidence")).toBeTruthy();
    expect(screen.getByText("Open classroom setup").getAttribute("href")).toBe("/classroom-setup");
    expect(screen.queryByRole("table", { name: /regions/i })).toBeNull();
  });
});

describe("Artifacts tab and deletion", () => {
  it("lists only artifacts the server confirmed and downloads them through the API client", async () => {
    mockApi(); download.mockResolvedValue("session_203.pdf");
    renderPage("/sessions/203?tab=artifacts");
    await ready();
    const panel = within(await screen.findByRole("tabpanel"));
    expect((await panel.findAllByText("Annotated video")).length).toBeGreaterThan(0);
    expect(panel.getByText(/annotated_203\.mp4 · 5\.0 MB/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Download Report (PDF)"));
    await waitFor(() => expect(download).toHaveBeenCalledWith("/api/sessions/203/report?format=pdf", "session_203.pdf"));
    expect(await screen.findByText("Report (PDF) downloaded.")).toBeTruthy();
  });

  it("still renders the page when the artifact list fails to load", async () => {
    mockApi({ artifacts: new Error("boom") }); renderPage("/sessions/203?tab=artifacts");
    await ready();
    expect(await screen.findByText(/No stored artifacts were found for this session/)).toBeTruthy();
  });

  it("requires a typed confirmation before deleting selected files, keeps evidence, and refreshes", async () => {
    mockApi(); del.mockResolvedValue({ data: { kinds: ["reports"] } } as any);
    renderPage("/sessions/203?tab=artifacts");
    await ready();
    const remove = (await screen.findByText("Delete selected files…")) as HTMLButtonElement;
    expect(remove.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Generated reports"));
    expect(remove.disabled).toBe(false);
    fireEvent.click(remove);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Analytics evidence is kept/)).toBeTruthy();
    const confirm = within(dialog).getByText("Delete files") as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(del).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Type DELETE to confirm"), { target: { value: "DELETE" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(del).toHaveBeenCalledWith("/v1/sessions/203/artifacts", { params: { kinds: "reports", confirm: true } }));
    expect(await screen.findByText(/analytics evidence was kept/)).toBeTruthy();
    await waitFor(() => expect(callsTo("/artifacts")).toBeGreaterThan(1)); // the list is re-read after deletion
  });

  it("hides file deletion from viewers", async () => {
    mockApi({ role: "VIEWER" }); renderPage("/sessions/203?tab=artifacts");
    await ready();
    expect(await within(await screen.findByRole("tabpanel")).findByText("Annotated video")).toBeTruthy();
    expect(screen.queryByText("Delete selected files…")).toBeNull();
  });

  it("deletes a whole session only after typing DELETE, then returns to the list", async () => {
    mockApi(); del.mockResolvedValue({ data: { status: "deleted" } } as any);
    renderPage();
    await ready();
    await waitFor(() => expect((screen.getByText("Delete").closest("button") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Delete"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/permanently deletes/)).toBeTruthy();
    expect(within(dialog).getByText(/recorded in the audit trail/)).toBeTruthy();
    fireEvent.click(within(dialog).getByText("Cancel"));
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Delete"));
    const second = await screen.findByRole("dialog");
    fireEvent.change(within(second).getByLabelText("Type DELETE to confirm"), { target: { value: "DELETE" } });
    fireEvent.click(within(second).getByText("Delete session"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/sessions/203", { params: { confirm: true } }));
    expect(await screen.findByText("Sessions list")).toBeTruthy();
  });

  it("does not allow deleting a session that is still processing", async () => {
    mockApi({ session: { ...SESSION, status: "PROCESSING" } }); renderPage();
    await ready();
    await waitFor(() => expect((screen.getByText("Delete").closest("button") as HTMLButtonElement).disabled).toBe(true));
  });
});

describe("Notes tab", () => {
  const NOTE = { id: 7, body: "First observation", review_status: "OPEN", version: 2, edited: true, created_at: "2026-09-02T10:00:00", updated_at: "2026-09-03T10:00:00", can_edit: true, author: { id: 1, display_name: "Ada Admin", role: "ADMINISTRATOR" } };
  it("shows author, role, time and edit state, and lets an authorized user add and edit notes", async () => {
    mockApi({ notes: [NOTE] }); post.mockResolvedValue({ data: {} } as any); vi.mocked(api.put).mockResolvedValue({ data: {} } as any);
    renderPage("/sessions/203?tab=notes");
    await ready();
    const item = (await screen.findByText("First observation")).closest("li")!;
    expect(within(item).getByText("Ada Admin")).toBeTruthy();
    expect(within(item).getByText(/administrator/)).toBeTruthy();
    expect(within(item).getByText(/edited .* \(v2\)/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Add a note"), { target: { value: "  Second note  " } });
    fireEvent.click(screen.getByText("Save note"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/notes", { scope_type: "SESSION", scope_id: 203, body: "Second note" }));
    await screen.findByText("Note saved.");
    fireEvent.click(await screen.findByLabelText("Edit note by Ada Admin"));
    fireEvent.change(screen.getByLabelText("Edit note"), { target: { value: "Revised" } });
    fireEvent.click(screen.getByText("Save changes"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/v1/notes/7", { body: "Revised", review_status: "OPEN", version: 2 }));
  });

  it("shows no edit control when the server says the note is not editable, and no form for viewers", async () => {
    mockApi({ role: "VIEWER", notes: [{ ...NOTE, can_edit: false }] });
    renderPage("/sessions/203?tab=notes");
    await ready();
    expect(await screen.findByText("First observation")).toBeTruthy();
    expect(screen.queryByLabelText(/Edit note by/)).toBeNull();
    expect(screen.getByText(/Your role can read notes but not add them/)).toBeTruthy();
    expect(screen.queryByText("Save note")).toBeNull();
  });
});
