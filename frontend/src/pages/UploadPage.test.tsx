// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../services/api";
import { UploadPage } from "./UploadPage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const get = vi.mocked(api.get), post = vi.mocked(api.post);

function renderPage() {
  return render(<MemoryRouter><UploadPage /></MemoryRouter>);
}

function mockLists() {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u.includes("/health")) return { data: { max_upload_mb: 500, max_video_duration_minutes: 180 } } as any;
    if (u.includes("/v1/classrooms")) return { data: [{ id: 1, name: "Room 204" }] } as any;
    if (u.includes("/v1/courses")) return { data: [{ id: 1, code: "CS101", name: "Intro" }] } as any;
    return { data: [] } as any;
  });
}

function makeFile(name: string, type: string, sizeBytes: number) {
  const file = new File([new Uint8Array(Math.max(1, sizeBytes))], name, { type });
  Object.defineProperty(file, "size", { value: sizeBytes });
  return file;
}

afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers(); });

describe("UploadPage", () => {
  it("rejects an unsupported file extension", async () => {
    mockLists();
    renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile("clip.txt", "text/plain", 1000);
    await act(async () => fireEvent.change(input, { target: { files: [file] } }));
    expect(await screen.findByText(/Unsupported file type/)).toBeTruthy();
  });

  it("rejects an oversized file against the real backend limit", async () => {
    mockLists();
    renderPage();
    await waitFor(() => expect(get).toHaveBeenCalled());
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile("big.mp4", "video/mp4", 600 * 1024 * 1024);
    await act(async () => fireEvent.change(input, { target: { files: [file] } }));
    expect(await screen.findByText(/exceeds the 500 MB/)).toBeTruthy();
  });

  it("rejects an empty file", async () => {
    mockLists();
    renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile("empty.mp4", "video/mp4", 0);
    await act(async () => fireEvent.change(input, { target: { files: [file] } }));
    expect(await screen.findByText(/is empty/)).toBeTruthy();
  });

  it("accepts a valid file, shows its details, and allows removal", async () => {
    mockLists();
    renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile("clip.mp4", "video/mp4", 2048);
    await act(async () => fireEvent.change(input, { target: { files: [file] } }));
    expect(await screen.findByText("clip.mp4")).toBeTruthy();
    fireEvent.click(screen.getByText("Remove"));
    await waitFor(() => expect(screen.queryByText("clip.mp4")).toBeNull());
  });

  it("disables upload until consent is confirmed", async () => {
    mockLists();
    renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => fireEvent.change(input, { target: { files: [makeFile("clip.mp4", "video/mp4", 2048)] } }));
    await screen.findByText("clip.mp4");
    const submit = screen.getByText(/Upload and queue analysis/);
    expect((submit.closest("button") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect((submit.closest("button") as HTMLButtonElement).disabled).toBe(false));
  });

  it("shows distinct upload progress and then processing progress", async () => {
    mockLists();
    let resolveUpload: (v: any) => void = () => {};
    post.mockImplementation(() => new Promise((r) => { resolveUpload = r; }));
    get.mockImplementation(async (url: any) => {
      const u = String(url);
      if (u.includes("/health")) return { data: { max_upload_mb: 500, max_video_duration_minutes: 180 } } as any;
      if (u.includes("/jobs/")) return { data: { job_id: "job1", session_id: 42, status: "PROCESSING", stage: "DECODING", progress: 40, processed_frames: 40, total_frames: 100 } } as any;
      return { data: [] } as any;
    });
    renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => fireEvent.change(input, { target: { files: [makeFile("clip.mp4", "video/mp4", 2048)] } }));
    await screen.findByText("clip.mp4");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText(/Upload and queue analysis/));
    expect(await screen.findByText(/UPLOADING \(file transfer, not analysis\)/)).toBeTruthy();
    resolveUpload({ data: { id: 42, job_id: "job1", total_frames: 100 } });
    expect(await screen.findByText("4. Processing")).toBeTruthy();
    expect(await screen.findByText(/40 \/ 100 frames/)).toBeTruthy();
  });

  it("shows the completed state with artifact actions enabled", async () => {
    mockLists();
    post.mockResolvedValue({ data: { id: 42, job_id: "job1", total_frames: 100 } } as any);
    get.mockImplementation(async (url: any) => {
      const u = String(url);
      if (u.includes("/health")) return { data: { max_upload_mb: 500, max_video_duration_minutes: 180 } } as any;
      if (u.includes("/jobs/")) return { data: { job_id: "job1", session_id: 42, status: "COMPLETED", stage: "COMPLETED", progress: 100, report_ready: true } } as any;
      return { data: [] } as any;
    });
    renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => fireEvent.change(input, { target: { files: [makeFile("clip.mp4", "video/mp4", 2048)] } }));
    await screen.findByText("clip.mp4");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText(/Upload and queue analysis/));
    expect(await screen.findByText("Open session")).toBeTruthy();
    expect(screen.getByText("View report")).toBeTruthy();
  });

  it("shows the failed state with a retry action", async () => {
    mockLists();
    post.mockResolvedValue({ data: { id: 42, job_id: "job1", total_frames: 100 } } as any);
    get.mockImplementation(async (url: any) => {
      const u = String(url);
      if (u.includes("/health")) return { data: { max_upload_mb: 500, max_video_duration_minutes: 180 } } as any;
      if (u.includes("/jobs/")) return { data: { job_id: "job1", session_id: 42, status: "FAILED", stage: "FAILED", error: "Video decoding failed.", failure_code: "VIDEO_DECODING_FAILED" } } as any;
      return { data: [] } as any;
    });
    renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => fireEvent.change(input, { target: { files: [makeFile("clip.mp4", "video/mp4", 2048)] } }));
    await screen.findByText("clip.mp4");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText(/Upload and queue analysis/));
    expect(await screen.findByText("Video decoding failed.")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("stops polling when the component unmounts", async () => {
    mockLists();
    post.mockResolvedValue({ data: { id: 42, job_id: "job1", total_frames: 100 } } as any);
    let jobCalls = 0;
    get.mockImplementation(async (url: any) => {
      const u = String(url);
      if (u.includes("/health")) return { data: { max_upload_mb: 500, max_video_duration_minutes: 180 } } as any;
      if (u.includes("/jobs/")) { jobCalls += 1; return { data: { job_id: "job1", session_id: 42, status: "PROCESSING", stage: "PROCESSING", progress: 10 } } as any; }
      return { data: [] } as any;
    });
    const { unmount } = renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => fireEvent.change(input, { target: { files: [makeFile("clip.mp4", "video/mp4", 2048)] } }));
    await screen.findByText("clip.mp4");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText(/Upload and queue analysis/));
    await waitFor(() => expect(jobCalls).toBeGreaterThan(0));
    unmount();
    const callsAtUnmount = jobCalls;
    await new Promise((r) => setTimeout(r, 1700));
    expect(jobCalls).toBe(callsAtUnmount);
  });

  it("gives the file input an accessible name", async () => {
    mockLists();
    renderPage();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.getAttribute("aria-label")).toBe("Choose a classroom video file");
    expect(screen.getByLabelText("Choose a classroom video file")).toBe(input);
  });

  it("lays the configuration out with the responsive two-column class, not an inline grid template", async () => {
    mockLists();
    renderPage();
    await waitFor(() => expect(get).toHaveBeenCalled());
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => fireEvent.change(input, { target: { files: [makeFile("clip.mp4", "video/mp4", 2048)] } }));
    expect(await screen.findByText("2. Configure session")).toBeTruthy();   // the configuration grid appears once a file is chosen
    const grid = document.querySelector(".settings-grid.two-up") as HTMLElement;
    expect(grid).toBeTruthy();
    expect(grid.style.gridTemplateColumns).toBe("");   // an inline template would override the small-screen media query
  });
});
