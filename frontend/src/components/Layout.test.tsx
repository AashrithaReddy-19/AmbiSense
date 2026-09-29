// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { ThemeProvider } from "../theme/ThemeContext";
import { api } from "../services/api";
import { Layout } from "./Layout";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const get = vi.mocked(api.get);

afterEach(() => { cleanup(); localStorage.clear(); });

function mockApi({ role = "ADMINISTRATOR", authEnabled = false, notifications = [] as any[], health = { status: "ok" } as any, unreadHeader = undefined as string | undefined } = {}) {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u.includes("/v1/auth/me")) return { data: { id: 1, email: "user@test", display_name: "Test User", role, auth_enabled: authEnabled } } as any;
    if (u.includes("/v1/notifications")) return { data: notifications, headers: unreadHeader === undefined ? {} : { "x-unread-count": unreadHeader } } as any;
    if (u.includes("/health")) return { data: health } as any;
    return { data: [] } as any;
  });
}

function renderShell(initialPath = "/dashboard") {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="dashboard" element={<div>Overview content</div>} />
              <Route path="sessions" element={<div>Sessions content</div>} />
              <Route path="settings" element={<div>Settings content</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("Layout shell", () => {
  beforeEach(() => mockApi());

  it("highlights the active navigation route", async () => {
    renderShell("/dashboard");
    const link = await screen.findByRole("link", { name: "Overview" });
    expect(link.className).toContain("active");
  });

  it("collapses and expands the sidebar, persisting the preference", async () => {
    renderShell();
    await screen.findByText("Overview content");
    const toggle = screen.getByLabelText("Collapse navigation");
    fireEvent.click(toggle);
    expect(document.querySelector(".shell")?.className).toContain("collapsed");
    expect(localStorage.getItem("ambisense_nav_collapsed")).toBe("1");
    fireEvent.click(screen.getByLabelText("Expand navigation"));
    expect(document.querySelector(".shell")?.className).not.toContain("collapsed");
  });

  it("opens the mobile drawer and closes it on Escape", async () => {
    renderShell();
    await screen.findByText("Overview content");
    fireEvent.click(screen.getByLabelText("Open navigation menu"));
    expect(screen.getByRole("dialog", { name: "Navigation" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull());
  });

  it("locks body scroll while the mobile drawer is open", async () => {
    renderShell();
    await screen.findByText("Overview content");
    fireEvent.click(screen.getByLabelText("Open navigation menu"));
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(document.body.style.overflow).not.toBe("hidden"));
  });

  it("shows Settings for an Administrator", async () => {
    mockApi({ role: "ADMINISTRATOR" });
    renderShell();
    await screen.findByText("Overview content");
    expect(screen.queryByRole("link", { name: "Settings" })).toBeTruthy();
  });

  it("hides Settings and Upload for a Viewer", async () => {
    mockApi({ role: "VIEWER" });
    renderShell();
    await screen.findByText("Overview content");
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Upload & Process" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Sessions" })).toBeTruthy(); // still visible to all roles
  });

  it("shows a development-mode badge when authentication is disabled", async () => {
    mockApi({ authEnabled: false });
    renderShell();
    expect(await screen.findByText(/DEV MODE/)).toBeTruthy();
  });

  it("does not show a development-mode badge when authentication is enabled", async () => {
    mockApi({ authEnabled: true });
    renderShell();
    await screen.findByText("Overview content");
    expect(screen.queryByText(/DEV MODE/)).toBeNull();
  });

  it("shows the real unread notification count, not a hard-coded badge", async () => {
    // The API reports `read: boolean` (there is no read_at field), so the bell must count that.
    mockApi({ notifications: [{ id: 1, title: "A", message: "a", read: false }, { id: 2, title: "B", message: "b", read: true }] });
    renderShell();
    expect(await screen.findByLabelText("Notifications, 1 unread")).toBeTruthy();
  });

  it("prefers the server's total unread count over the few notifications previewed", async () => {
    mockApi({ notifications: [{ id: 1, title: "A", message: "a", read: false }], unreadHeader: "42" });
    renderShell();
    expect(await screen.findByLabelText("Notifications, 42 unread")).toBeTruthy();
  });

  it("shows no unread badge when there are no notifications", async () => {
    mockApi({ notifications: [] });
    renderShell();
    await screen.findByText("Overview content");
    expect(screen.getByLabelText("Notifications")).toBeTruthy();
  });

  it("renders breadcrumbs for a nested route", async () => {
    renderShell("/sessions");
    await screen.findByText("Sessions content");
    expect(screen.getByText("Sessions", { selector: ".current" })).toBeTruthy();
  });

  it("shows a connected backend status once the health check succeeds", async () => {
    mockApi({ health: { status: "ok" } });
    renderShell();
    await waitFor(() => expect(screen.getByLabelText(/Backend connection: Connected/)).toBeTruthy());
  });

  it("shows a disconnected backend status when the health check fails", async () => {
    get.mockImplementation(async (url: any) => {
      const u = String(url);
      if (u.includes("/v1/auth/me")) return { data: { id: 1, email: "user@test", role: "ADMINISTRATOR", auth_enabled: false } } as any;
      if (u.includes("/health")) throw new Error("network error");
      return { data: [] } as any;
    });
    renderShell();
    await waitFor(() => expect(screen.getByLabelText(/Backend connection: Disconnected/)).toBeTruthy());
  });
});
