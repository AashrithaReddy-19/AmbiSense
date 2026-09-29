// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/Toast";
import { api } from "../services/api";
import { SettingsPage, toDraft, validateEntry } from "./SettingsPage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
const get = vi.mocked(api.get), post = vi.mocked(api.post), put = vi.mocked(api.put);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const entry = (o: Record<string, unknown>) => ({ kind: "number", unit: null, min: null, max: null, choices: null, editable: true, restart_required: false, risky: false, description: "", source: undefined, ...o });
const GROUPS = ["General", "Analytics", "Models", "Thresholds", "Privacy & Retention", "Reports", "Optional Audio", "Feature Flags", "System"];
const SETTINGS = [
  entry({ key: "expected_students", group: "General", label: "Expected students", unit: "people", min: 1, max: 500, value: 40 }),
  entry({ key: "show_overlays", group: "Reports", label: "Show overlays on annotated video", kind: "boolean", value: true }),
  entry({ key: "ear_threshold", group: "Thresholds", label: "Eye-aspect-ratio threshold", unit: "ratio", min: 0.05, max: 0.6, risky: true, value: 0.21, description: "Below this an eye is treated as closed." }),
  entry({ key: "retention_days", group: "Privacy & Retention", label: "Session retention period", unit: "days", min: 1, max: 3650, risky: true, value: 30 }),
  entry({ key: "transcription_provider", group: "Optional Audio", label: "Transcription provider", kind: "choice", choices: ["NONE", "FASTER_WHISPER"], risky: true, value: "NONE" }),
  entry({ key: "demo_mode", group: "Feature Flags", label: "Demo mode", kind: "boolean", risky: true, value: false }),
  entry({ key: "max_upload_mb", group: "Reports", label: "Maximum upload size", unit: "MB", editable: false, restart_required: true, kind: "readonly", source: "environment", value: 500 }),
  entry({ key: "auth_enabled", group: "System", label: "Authentication enabled", editable: false, restart_required: true, kind: "readonly", source: "environment", value: false }),
];
const CATALOG = { groups: GROUPS, settings: SETTINGS, audio: { status: "DISABLED", reason: "Audio analytics is disabled (AUDIO_ANALYTICS_ENABLED=false).", audio_processing_enabled: false, ffmpeg_available: false, transcription: { configured: false, provider: "NONE", model_available: false }, diarization: { configured: false, provider: "NONE", model_available: false } }, notice: "Threshold changes apply to new processing jobs only and never alter stored evidence." };
const VALUES = { expected_students: 40, show_overlays: true, ear_threshold: 0.21, retention_days: 30, transcription_provider: "NONE", demo_mode: false, total_seats: 40 };
const POLICY = { retention_days: 30, cutoff: "2026-08-28T00:00:00", eligible_sessions: [{ id: 3, name: "Old session", created_at: "2026-06-01T00:00:00" }], action: "ARCHIVE", transcripts: { enabled: true, days: 30 }, test_sessions: { scheduled_enabled: false, cleanup_enabled: false, action: "ARCHIVE", age_hours: 24 } };
const DIAGNOSTICS = { database: { dialect: "sqlite", alembic_revision: "20260920_backfill_legacy_constraints" }, readiness: { status: "ready", checks: { database: { ok: true }, models: { ok: true } } }, worker: { mode: "IN_PROCESS", durable: false, queue_depth: 0, stale_jobs: 2, healthy: true }, configuration: { issues: [{ level: "WARNING", setting: "AUTH_ENABLED", message: "Authentication is disabled: every caller acts as a local administrator." }] } };

const STALE = {
  explanation: "Jobs run inside the API process, so work that was in progress when the server stopped or restarted cannot continue. These sessions still claim to be running but nothing is processing them.",
  runner: { mode: "IN_PROCESS", durable: false }, total: 3, recoverable: 2,
  items: [
    { id: 11, name: "Lecture video A", source_type: "VIDEO", status: "PROCESSING", processing_stage: "PROCESSING", age_minutes: 200, kind: "STALE_VIDEO_JOB", recoverable: true, reason: "No worker is processing this video job. Marking it failed lets you retry it." },
    { id: 12, name: "Lecture video B", source_type: "VIDEO", status: "DECODING", processing_stage: "DECODING", age_minutes: 45, kind: "STALE_VIDEO_JOB", recoverable: true, reason: "No worker is processing this video job. Marking it failed lets you retry it." },
    { id: 13, name: "Live classroom C", source_type: "LIVE", status: "PROCESSING", processing_stage: "CAPTURING_LIVE_CAMERA", age_minutes: 900, kind: "LIVE_CAPTURE_INTERRUPTED", recoverable: false, reason: "The live camera connection ended without a clean stop. A live capture cannot be resumed, so this session is left unchanged." },
  ],
  not_running: { STOPPED: 4, CREATED: 2, note: "" },
};

function mockApi(overrides: Record<string, any> = {}) {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u in overrides) { const value = overrides[u]; if (value?.response) throw value; return { data: value } as any; }
    if (u.includes("/v1/settings/catalog")) return { data: CATALOG } as any;
    if (u === "/settings") return { data: VALUES } as any;
    if (u.includes("/models/health")) return { data: { device: "CPU", mode: "REAL", models: [{ name: "YOLOv8", loaded: true, path: "yolov8n.pt" }, { name: "Faster Whisper", loaded: false, path: "base" }] } } as any;
    if (u.includes("/retention/policy")) return { data: POLICY } as any;
    if (u.includes("/system/jobs/stale")) return { data: STALE } as any;
    if (u.includes("/system/diagnostics")) return { data: DIAGNOSTICS } as any;
    if (u.includes("/evaluation/status")) return { data: { validated: false, headline: "Not validated on real classroom footage.", detail: "No verified accuracy or fairness result is currently available.", fairness: "NOT_EVALUATED" } } as any;
    return { data: [] } as any;
  });
}
const renderPage = () => render(<ToastProvider><SettingsPage /></ToastProvider>);
const openTab = (name: string) => fireEvent.click(screen.getByRole("tab", { name: new RegExp(`^${name.replace(/[&]/g, "\\$&")}`) }));
const save = () => fireEvent.click(screen.getByText("Save changes"));

describe("validateEntry / toDraft", () => {
  const expected = SETTINGS[0] as any, ear = SETTINGS[2] as any, provider = SETTINGS[4] as any;
  it("checks range, integer-ness, choices and emptiness", () => {
    expect(validateEntry(expected, "40")).toBeNull();
    expect(validateEntry(expected, "0")).toBe("Must be at least 1 people.");
    expect(validateEntry(expected, "501")).toBe("Must be at most 500 people.");
    expect(validateEntry(expected, "12.5")).toBe("Must be a whole number.");
    expect(validateEntry(expected, "")).toBe("Enter a number.");
    expect(validateEntry(ear, "0.7")).toMatch(/at most 0\.6/);
    expect(validateEntry(provider, "OPENAI")).toMatch(/Choose one of/);
    expect(validateEntry(SETTINGS[6] as any, "anything")).toBeNull(); // read-only values are never validated
  });
  it("seeds a draft only from editable settings", () => {
    const draft = toDraft(SETTINGS as any);
    expect(draft.expected_students).toBe("40");
    expect(draft.show_overlays).toBe(true);
    expect("max_upload_mb" in draft).toBe(false);
  });
});

describe("SettingsPage", () => {
  it("organises supported settings into the nine required groups", async () => {
    mockApi(); renderPage();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent?.replace(/\d+$/, ""))).toEqual(GROUPS);
    expect(screen.getByLabelText("Expected students")).toBeTruthy();
    openTab("Thresholds");
    expect(screen.getByLabelText("Eye-aspect-ratio threshold")).toBeTruthy();
    expect(screen.getByText(/Range 0\.05–0\.6/)).toBeTruthy();
    expect(screen.getByText(/Unit: ratio/)).toBeTruthy();
    expect(screen.getByText(/They are not validated on real classroom footage/)).toBeTruthy();
  });

  it("marks environment-controlled values read-only with a restart-required flag and no input", async () => {
    mockApi(); renderPage();
    await screen.findAllByRole("tab");
    openTab("Reports");
    const row = screen.getByText("Maximum upload size").closest(".region-row") as HTMLElement;
    expect(within(row).getByText(/Read-only · set by environment/)).toBeTruthy();
    expect(within(row).getByText("Restart required")).toBeTruthy();
    expect(within(row).queryByRole("spinbutton")).toBeNull();
    expect(within(row).getByText("500 MB")).toBeTruthy();
  });

  it("never shows secrets", async () => {
    mockApi(); renderPage();
    await screen.findAllByRole("tab");
    for (const name of GROUPS) { openTab(name); expect(document.body.textContent).not.toMatch(/AUTH_SECRET_KEY|secret_key|redis_url|database_url|password/i); }
  });

  it("validates units and ranges inline and blocks saving", async () => {
    mockApi(); renderPage();
    fireEvent.change(await screen.findByLabelText("Expected students"), { target: { value: "900" } });
    expect(screen.getByText("Must be at most 500 people.")).toBeTruthy();
    expect(screen.getByLabelText("Expected students").getAttribute("aria-invalid")).toBe("true");
    expect((screen.getByText("Save changes").closest("button") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Fix the highlighted values to save.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Expected students"), { target: { value: "35" } });
    expect((screen.getByText("Save changes").closest("button") as HTMLButtonElement).disabled).toBe(false);
  });

  it("saves a non-risky change immediately with the full payload and no risk confirmation", async () => {
    mockApi(); put.mockResolvedValue({ data: { settings: { ...VALUES, expected_students: 35 }, changes: {} } } as any);
    renderPage();
    fireEvent.change(await screen.findByLabelText("Expected students"), { target: { value: "35" } });
    expect(screen.getByText("1 unsaved change.")).toBeTruthy();
    save();
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put).toHaveBeenCalledWith("/settings", { ...VALUES, expected_students: 35 }, { params: undefined });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await screen.findByText(/Saved 1 setting\. They apply to new processing jobs; earlier results are unchanged\./)).toBeTruthy();
  });

  it("requires an explicit confirmation for a risky change and sends the confirm flag only afterwards", async () => {
    mockApi(); put.mockResolvedValue({ data: { settings: { ...VALUES, ear_threshold: 0.25 }, changes: {} } } as any);
    renderPage();
    await screen.findAllByRole("tab");
    openTab("Thresholds");
    fireEvent.change(screen.getByLabelText("Eye-aspect-ratio threshold"), { target: { value: "0.25" } });
    expect(screen.getByText("Affects new results")).toBeTruthy();
    save();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/0\.21 → 0\.25 ratio/)).toBeTruthy();
    expect(within(dialog).getByText(/recorded in the audit trail/)).toBeTruthy();
    expect(put).not.toHaveBeenCalled(); // nothing changes silently
    fireEvent.click(within(dialog).getByText("Cancel"));
    expect(put).not.toHaveBeenCalled();
    save();
    fireEvent.click(within(await screen.findByRole("dialog")).getByText("Apply changes"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/settings", { ...VALUES, ear_threshold: 0.25 }, { params: { confirm_risky: true } }));
  });

  it("shows unsaved counts on tabs and Discard restores the saved values", async () => {
    mockApi(); renderPage();
    await screen.findAllByRole("tab");
    fireEvent.change(screen.getByLabelText("Expected students"), { target: { value: "20" } });
    expect(screen.getByRole("tab", { name: /^General1$/ })).toBeTruthy();
    fireEvent.click(screen.getByText("Discard"));
    expect((screen.getByLabelText("Expected students") as HTMLInputElement).value).toBe("40");
    expect(screen.getByText("No unsaved changes.")).toBeTruthy();
  });

  it("warns when demo mode is switched on or privacy would be weakened", async () => {
    mockApi(); renderPage();
    await screen.findAllByRole("tab");
    openTab("Feature Flags");
    fireEvent.click(screen.getByLabelText("Off"));
    expect(screen.getByText(/synthetic DEMO sessions/)).toBeTruthy();
  });

  it("shows the server's message when saving fails", async () => {
    mockApi(); put.mockRejectedValue({ response: { status: 422, data: { error: { code: "VALIDATION_FAILED", message: "Request validation failed." } } } });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Expected students"), { target: { value: "35" } });
    save();
    expect((await screen.findAllByText("Request validation failed.")).length).toBeGreaterThan(0);
  });

  it("shows retention policy, requires confirmation to archive, and states nothing is deleted", async () => {
    mockApi(); post.mockResolvedValue({ data: { archived: 1, session_ids: [3] } } as any);
    renderPage();
    await screen.findAllByRole("tab");
    openTab("Privacy & Retention");
    expect(await screen.findByText(/older than/)).toBeTruthy();
    expect(screen.getByText(/deleted only by an explicit action on a single session/)).toBeTruthy();
    expect(screen.getByText(/#3 · Old session/)).toBeTruthy();
    expect(screen.getByText(/policy is 30 days, applied only when you run it \(scheduled cleanup is off\)/)).toBeTruthy();
    expect(screen.getByText(/no automatic cleanup \(starting the server never changes existing sessions\)/)).toBeTruthy();
    fireEvent.click(screen.getByText("Archive 1 session(s)…"));
    expect(post).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/kept and they can be restored/)).toBeTruthy();
    fireEvent.click(within(dialog).getByText("Archive sessions"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/retention/sessions/run", null, { params: { confirm: true } }));
    expect(await screen.findByText(/Archived 1 session\(s\)\. Nothing was deleted\./)).toBeTruthy();
  });

  it("shows model health and the optional-audio capability state", async () => {
    mockApi(); renderPage();
    await screen.findAllByRole("tab");
    openTab("Models");
    expect(await screen.findByText("Loaded")).toBeTruthy();
    expect(screen.getByText("Unavailable")).toBeTruthy();
    openTab("Optional Audio");
    expect(screen.getByText("Disabled")).toBeTruthy();
    expect(screen.getByText(/Audio analytics is disabled/)).toBeTruthy();
  });

  it("shows diagnostics and the not-validated statement", async () => {
    mockApi(); renderPage();
    await screen.findAllByRole("tab");
    openTab("System");
    expect(await screen.findByText(/sqlite · migration 20260920_backfill_legacy_constraints/)).toBeTruthy();
    expect(screen.getByText(/not durable \(jobs end if the server restarts\)/)).toBeTruthy();
    expect(screen.getByText("AUTH_ENABLED")).toBeTruthy();
    expect(screen.getByText("Not validated on real classroom footage.")).toBeTruthy();
  });

  it("previews stale sessions, explains why, and never changes anything until a selection is confirmed", async () => {
    mockApi(); post.mockResolvedValue({ data: { count: 2, recovered_session_ids: [11, 12] } } as any);
    renderPage();
    await screen.findAllByRole("tab");
    openTab("System");
    expect(await screen.findByRole("heading", { name: /Sessions that look stuck \(3\)/ })).toBeTruthy();
    expect(screen.getByText(/cannot continue/)).toBeTruthy();
    expect(screen.getByText(/Nothing has been changed/)).toBeTruthy();
    expect(screen.getAllByText("Stale")).toHaveLength(3);
    expect(screen.getByRole("checkbox", { name: "Select Lecture video A (#11)" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /Live classroom C/ })).toBeNull(); // live captures cannot be recovered here
    expect(screen.getByText("Left unchanged")).toBeTruthy();
    expect(screen.getByText(/4 stopped and 2 created live session\(s\) are not running jobs/)).toBeTruthy();
    fireEvent.click(screen.getByText("Mark 2 selected job(s) as failed…"));
    expect(post).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/#11 · Lecture video A/)).toBeTruthy();
    expect(within(dialog).getByText(/#12 · Lecture video B/)).toBeTruthy();
    expect(within(dialog).queryByText(/Live classroom C/)).toBeNull();
    expect(within(dialog).getByText(/recorded in the audit trail/)).toBeTruthy();
    fireEvent.click(within(dialog).getByText("Mark as failed"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/system/jobs/recover", null, { params: { confirm: true, session_ids: [11, 12] }, paramsSerializer: { indexes: null } }));
  });

  it("recovers only the sessions left selected, and cannot be confirmed with none selected", async () => {
    mockApi(); post.mockResolvedValue({ data: { count: 1, recovered_session_ids: [12] } } as any);
    renderPage();
    await screen.findAllByRole("tab");
    openTab("System");
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Lecture video A (#11)" }));
    fireEvent.click(screen.getByText("Mark 1 selected job(s) as failed…"));
    fireEvent.click(within(await screen.findByRole("dialog")).getByText("Mark as failed"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/system/jobs/recover", null, { params: { confirm: true, session_ids: [12] }, paramsSerializer: { indexes: null } }));
    cleanup(); vi.resetAllMocks(); mockApi(); renderPage();
    await screen.findAllByRole("tab"); openTab("System");
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Lecture video A (#11)" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Lecture video B (#12)" }));
    expect((screen.getByText("Mark 0 selected job(s) as failed…") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows no stale-session panel when nothing is stuck", async () => {
    mockApi({ "/v1/system/jobs/stale": { ...STALE, total: 0, recoverable: 0, items: [] } }); renderPage();
    await screen.findAllByRole("tab");
    openTab("System");
    await screen.findByText(/sqlite · migration/);
    expect(screen.queryByRole("heading", { name: /Sessions that look stuck/ })).toBeNull();
  });

  it("shows an unauthorized state for non-administrators and an error with retry", async () => {
    mockApi({ "/v1/settings/catalog": { response: { status: 403, data: { error: { message: "Administrator permission required" } } } } });
    renderPage();
    expect(await screen.findByText("Only administrators can view settings")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    mockApi({ "/v1/settings/catalog": { response: { status: 500, data: { error: { message: "Settings backend down", request_id: "r1" } } } } });
    renderPage();
    expect(await screen.findByText("Settings backend down")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("shows the privacy and validation notices", async () => {
    mockApi(); renderPage();
    await screen.findAllByRole("tab");
    expect(screen.getByText(/does not identify students/)).toBeTruthy();
  });
});
