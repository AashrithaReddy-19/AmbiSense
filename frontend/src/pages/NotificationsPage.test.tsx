// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/Toast";
import { api } from "../services/api";
import { NotificationsPage } from "./NotificationsPage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const get = vi.mocked(api.get), post = vi.mocked(api.post);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const item = (overrides: Record<string, unknown> = {}) => ({ id: 1, category: "POOR_CAMERA", severity: "WARNING", title: "Poor camera quality", message: "Frames were dark for most of the session.", evidence: { mean_quality: 31 }, session_id: 5, link: "/sessions/5", read: false, dismissed: false, created_at: "2026-09-20T10:00:00", ...overrides });
const reply = (items: any[], headers: Record<string, string> = {}) => ({ data: items, headers: { "x-total-count": String(items.length), "x-unread-count": String(items.filter((row) => !row.read).length), ...headers } } as any);
const renderPage = (path = "/notifications") => render(<MemoryRouter initialEntries={[path]}><ToastProvider><NotificationsPage /></ToastProvider></MemoryRouter>);
const calls = () => get.mock.calls.filter(([url]) => String(url).includes("/v1/notifications"));
const lastParams = () => (calls().at(-1)?.[1] as any).params;

describe("NotificationsPage", () => {
  it("lists notifications with severity, category, deep link and unread state", async () => {
    get.mockResolvedValue(reply([item(), item({ id: 2, severity: "CRITICAL", title: "Processing failed", category: "PROCESSING_FAILED", read: true, link: null, session_id: 99 })]));
    renderPage();
    const list = await screen.findByRole("list", { name: "Notifications" });
    const [first, second] = within(list).getAllByRole("listitem");
    expect(within(first).getByText("Warning")).toBeTruthy();
    expect(within(first).getByText("Unread")).toBeTruthy();
    expect(within(first).getByText("Open session").getAttribute("href")).toBe("/sessions/5");
    expect(within(second).getByText("Critical")).toBeTruthy();
    expect(within(second).getByText("The linked session no longer exists.")).toBeTruthy(); // a dangling link is never rendered
    expect(within(second).queryByText("Unread")).toBeNull();
    expect(screen.getByText("1 unread")).toBeTruthy();
  });

  it("sends category, severity, status and dismissed filters only after Apply and preserves them across pages", async () => {
    get.mockResolvedValue(reply([item()], { "x-total-count": "40" }));
    renderPage();
    await screen.findByText("Poor camera quality");
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "POOR_CAMERA" } });
    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "warning" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "unread" } });
    fireEvent.change(screen.getByLabelText("Dismissed"), { target: { value: "yes" } });
    expect(lastParams().category).toBeUndefined();
    fireEvent.click(screen.getByText("Apply filters"));
    await waitFor(() => expect(lastParams()).toMatchObject({ category: "POOR_CAMERA", severity: "warning", read: false, include_dismissed: true, page: 1, page_size: 15 }));
    fireEvent.click(screen.getByLabelText("Next page"));
    await waitFor(() => expect(lastParams()).toMatchObject({ category: "POOR_CAMERA", page: 2 }));
    expect(screen.getByText(/Page 2 of 3/)).toBeTruthy();
  });

  it("marks one notification read and dismisses another, then reloads from the server", async () => {
    get.mockResolvedValue(reply([item()]));
    post.mockResolvedValue({ data: {} } as any);
    renderPage();
    fireEvent.click(await screen.findByText("Mark read"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/notifications/1/read"));
    expect(await screen.findByText("Marked as read.")).toBeTruthy();
    fireEvent.click(screen.getByText("Dismiss"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/notifications/1/dismiss"));
    await waitFor(() => expect(calls().length).toBeGreaterThanOrEqual(3)); // state is re-read from the server, not just patched locally
  });

  it("marks everything in the selected category as read in one request", async () => {
    get.mockResolvedValue(reply([item(), item({ id: 2 })]));
    post.mockResolvedValue({ data: { updated: 2 } } as any);
    renderPage("/notifications?category=POOR_CAMERA");
    fireEvent.click(await screen.findByText(/Mark all as read in category/));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/notifications/read-all", null, { params: { category: "POOR_CAMERA" } }));
    expect(await screen.findByText("Marked 2 notification(s) as read.")).toBeTruthy();
  });

  it("disables bulk read when nothing is unread", async () => {
    get.mockResolvedValue(reply([item({ read: true })]));
    renderPage();
    await screen.findByText("Poor camera quality");
    expect((screen.getByText(/Mark all as read/).closest("button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("runs the advisory check and reports deduplication honestly", async () => {
    get.mockResolvedValue(reply([]));
    post.mockResolvedValue({ data: { created: 0 } } as any);
    renderPage();
    fireEvent.click(await screen.findByText("Check sessions"));
    expect(await screen.findByText(/No new advisories/)).toBeTruthy();
    post.mockResolvedValue({ data: { created: 3 } } as any);
    fireEvent.click(screen.getByText("Check sessions"));
    expect(await screen.findByText(/3 new advisory notification\(s\) created\. Duplicates are skipped\./)).toBeTruthy();
  });

  it("shows an empty state, an error with retry, and a failed action toast", async () => {
    get.mockResolvedValueOnce(reply([]));
    renderPage();
    expect(await screen.findByText("No notifications")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    get.mockRejectedValueOnce({ response: { status: 500, data: { error: { message: "Notifications unavailable", request_id: "req-1" } } } });
    renderPage();
    expect(await screen.findByText("Notifications unavailable")).toBeTruthy();
    get.mockResolvedValue(reply([item()]));
    fireEvent.click(screen.getByText("Retry"));
    await screen.findByText("Poor camera quality");
    post.mockRejectedValue({ response: { status: 404, data: { detail: "Notification not found" } } });
    fireEvent.click(screen.getByText("Mark read"));
    expect(await screen.findByText("Notification not found")).toBeTruthy();
  });

  it("states that notifications are advisory, not conclusions", async () => {
    get.mockResolvedValue(reply([]));
    renderPage();
    expect(await screen.findByText(/prompts to review, not conclusions about anyone/)).toBeTruthy();
  });
});
