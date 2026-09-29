// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { FEATURES } from "../components/management/AccessPanel";
import { ToastProvider } from "../components/Toast";
import { api } from "../services/api";
import { ManagementPage } from "./ManagementPage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
const get = vi.mocked(api.get), post = vi.mocked(api.post), put = vi.mocked(api.put), del = vi.mocked(api.delete);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const USERS = [
  { id: 1, email: "admin@school.test", display_name: "Ada Admin", role: "ADMINISTRATOR", active: true, created_at: "2026-09-01T09:00:00" },
  { id: 2, email: "ian@school.test", display_name: "Ian Instructor", role: "INSTRUCTOR", active: true, created_at: "2026-09-02T09:00:00" },
];
const COURSE = { id: 3, code: "CS101", name: "Intro to CS", description: null, academic_term: "Fall", classroom_id: 1, active: true };
const ROOM = { id: 1, name: "Room 204", description: null, location_label: "Block A", active: true, capacity: 40, expected_students: 35 };
const PERMISSIONS = { auth_enabled: true, you: { role: "ADMINISTRATOR", permissions: ["*"] }, roles: [
  { role: "ADMINISTRATOR", summary: "Full access.", permissions: ["*"] }, { role: "INSTRUCTOR", summary: "Upload and manage own sessions.", permissions: ["session:view", "session:upload", "classroom:manage", "course:manage", "event:review", "note:write", "report:generate", "export"] },
  { role: "REVIEWER", summary: "Review.", permissions: ["session:view", "event:review", "note:write", "report:generate", "export"] }, { role: "VIEWER", summary: "Read only.", permissions: ["session:view", "report:generate"] },
] };

function mockApi({ role = "ADMINISTRATOR", authEnabled = true, userTotal = "2", users = USERS as any, failures = {} as Record<string, any> } = {}) {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    for (const [fragment, failure] of Object.entries(failures)) if (u.includes(fragment)) throw failure;
    if (u.includes("/v1/auth/me")) return { data: { id: role === "ADMINISTRATOR" ? 1 : 2, email: "me@school.test", display_name: "Me", role, auth_enabled: authEnabled } } as any;
    if (u.includes("/v1/auth/permissions")) return { data: { ...PERMISSIONS, you: { role, permissions: role === "ADMINISTRATOR" ? ["*"] : PERMISSIONS.roles.find((r) => r.role === role)!.permissions }, auth_enabled: authEnabled } } as any;
    if (u.includes("/v1/users")) return { data: users, headers: { "x-total-count": userTotal } } as any;
    if (u.includes("/members")) return { data: [{ user_id: 2, email: "ian@school.test", display_name: "Ian Instructor", membership_role: "REVIEWER", active: true }] } as any;
    if (u.match(/\/v1\/courses\/\d+\/sessions/)) return { data: [{ id: 9, name: "Assigned lecture", status: "COMPLETED", context: "LECTURE", created_at: "2026-09-10" }] } as any;
    if (u.includes("/v1/courses")) return { data: [COURSE] } as any;
    if (u.includes("/v1/classrooms")) return { data: [ROOM] } as any;
    if (u.includes("/v1/sessions")) return { data: { items: [{ id: 20, name: "Unassigned lecture", course_id: null }, { id: 21, name: "Already assigned", course_id: 3 }] } } as any;
    return { data: [] } as any;
  });
}
const renderPage = (path = "/management") => render(<MemoryRouter initialEntries={[path]}><AuthProvider><ToastProvider><ManagementPage /></ToastProvider></AuthProvider></MemoryRouter>);
const usersCalls = () => get.mock.calls.filter(([url]) => String(url) === "/v1/users");
const openTab = (name: RegExp) => fireEvent.click(screen.getByRole("tab", { name }));

describe("ManagementPage RBAC", () => {
  it("an administrator can open users, courses, classrooms and access", async () => {
    mockApi(); renderPage("/management?tab=users");
    expect(await screen.findByText("Ada Admin (you)")).toBeTruthy();
    expect(screen.getByText("Ian Instructor")).toBeTruthy();
    expect(screen.getByText("Add user")).toBeTruthy();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Courses", "Classrooms", "Users", "Access & permissions"]);
  });

  it("an instructor manages courses and classrooms but never requests or sees the user list", async () => {
    mockApi({ role: "INSTRUCTOR" }); renderPage();
    expect(await screen.findByText("CS101")).toBeTruthy();
    openTab(/^Users/);
    expect(await screen.findByText("Only administrators manage user accounts")).toBeTruthy();
    expect(usersCalls().length).toBe(0);
    openTab(/^Classrooms/);
    expect(await screen.findByText("Room 204")).toBeTruthy();
    expect(screen.getByText("Add classroom")).toBeTruthy();
  });

  it("a viewer gets explanations instead of management controls and no management requests", async () => {
    mockApi({ role: "VIEWER" }); renderPage();
    expect(await screen.findByText("Course management needs the instructor or administrator role")).toBeTruthy();
    expect(screen.queryByText("Add course")).toBeNull();
    openTab(/^Classrooms/);
    expect(await screen.findByText("Classroom management needs the instructor or administrator role")).toBeTruthy();
    expect(get.mock.calls.some(([url]) => String(url).includes("/v1/courses") || String(url) === "/v1/classrooms")).toBe(false);
    openTab(/^Access/);
    expect(await screen.findByText((_, element) => element?.tagName === "P" && /You are signed in as viewer/.test(element.textContent ?? ""))).toBeTruthy(); // everyone may read the permission explanations
  });

  it("warns prominently when authentication is disabled (development mode) and not when enabled", async () => {
    mockApi({ authEnabled: false }); renderPage();
    expect(await screen.findByText(/Development mode: authentication is disabled/)).toBeTruthy();
    expect(screen.getByText(/Every request acts as a local administrator/)).toBeTruthy();
    cleanup(); vi.resetAllMocks(); mockApi({ authEnabled: true }); renderPage();
    await screen.findByText("CS101");
    expect(screen.queryByText(/Development mode/)).toBeNull();
  });

  it("derives the feature-access matrix from the server's permissions", async () => {
    mockApi({ role: "INSTRUCTOR" }); renderPage("/management?tab=access");
    const table = await screen.findByRole("table", { name: "Feature access by role" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Feature", "administrator", "instructor (you)", "reviewer", "viewer"]);
    const row = (label: string) => within(table).getByText(label).closest("tr") as HTMLElement;
    const allowed = (label: string) => within(row(label)).getAllByRole("cell").map((cell) => cell.textContent);
    expect(allowed("Manage users and settings")).toEqual(["Allowed", "Not allowed", "Not allowed", "Not allowed"]);
    expect(allowed("Upload videos and start live sessions")).toEqual(["Allowed", "Allowed", "Not allowed", "Not allowed"]);
    expect(FEATURES.length).toBe(9);
  });
});

describe("Users panel", () => {
  it("searches, filters and paginates on the server using the total count", async () => {
    mockApi({ userTotal: "40" }); renderPage("/management?tab=users");
    await screen.findByText("Ada Admin (you)");
    fireEvent.change(screen.getByPlaceholderText("Name or email"), { target: { value: "ian" } });
    await waitFor(() => expect(usersCalls().at(-1)?.[1]).toMatchObject({ params: { q: "ian", page: 1, page_size: 15 } }));
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "INSTRUCTOR" } });
    await waitFor(() => expect(usersCalls().at(-1)?.[1]).toMatchObject({ params: { q: "ian", role: "INSTRUCTOR" } }));
    expect(screen.getByText(/Page 1 of 3 · 40 users/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Next page"));
    await waitFor(() => expect(usersCalls().at(-1)?.[1]).toMatchObject({ params: { page: 2, q: "ian", role: "INSTRUCTOR" } }));
  });

  it("validates a new user before enabling Create and never echoes the password", async () => {
    mockApi(); post.mockResolvedValue({ data: { id: 9 } } as any);
    renderPage("/management?tab=users");
    fireEvent.click(await screen.findByText("Add user"));
    const dialog = await screen.findByRole("dialog");
    const create = () => within(dialog).getByText("Create user") as HTMLButtonElement;
    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "not-an-email" } });
    fireEvent.change(within(dialog).getByLabelText("Display name"), { target: { value: "New Person" } });
    fireEvent.change(within(dialog).getByLabelText(/Initial password/), { target: { value: "short" } });
    expect(create().disabled).toBe(true);
    expect(within(dialog).getByText("Enter a valid email address.")).toBeTruthy();
    expect(within(dialog).getByText("The password must be at least 12 characters.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "new@school.test" } });
    fireEvent.change(within(dialog).getByLabelText(/Initial password/), { target: { value: "a-long-enough-password" } });
    expect(create().disabled).toBe(false);
    expect((within(dialog).getByLabelText(/Initial password/) as HTMLInputElement).type).toBe("password");
    fireEvent.click(create());
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/users", { email: "new@school.test", display_name: "New Person", role: "VIEWER", password: "a-long-enough-password" }));
    expect(await screen.findByText("User new@school.test created.")).toBeTruthy();
  });

  it("requires confirmation for a role change and for deactivation, and protects your own account", async () => {
    mockApi(); put.mockResolvedValue({ data: { id: 2 } } as any);
    renderPage("/management?tab=users");
    fireEvent.click(await screen.findByLabelText("Edit Ada Admin"));
    let dialog = await screen.findByRole("dialog");
    expect((within(dialog).getByLabelText("Role") as HTMLSelectElement).disabled).toBe(true);
    expect(within(dialog).getByText("You cannot change your own role.")).toBeTruthy();
    fireEvent.click(within(dialog).getByText("Cancel"));
    fireEvent.click(await screen.findByLabelText("Edit Ian Instructor"));
    dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Role"), { target: { value: "VIEWER" } });
    fireEvent.click(within(dialog).getByText("Save changes"));
    const confirm = await screen.findByText("Confirm access change");
    expect(put).not.toHaveBeenCalled();
    const confirmDialog = confirm.closest("[role=dialog]") as HTMLElement;
    expect(within(confirmDialog).getByText(/role instructor → viewer/)).toBeTruthy();
    expect(within(confirmDialog).getByText(/sign-in sessions are revoked immediately/)).toBeTruthy();
    fireEvent.click(within(confirmDialog).getByText("Apply change"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/v1/users/2", { display_name: "Ian Instructor", role: "VIEWER", active: true }));
  });

  it("surfaces the server's last-administrator protection", async () => {
    mockApi(); put.mockRejectedValue({ response: { status: 409, data: { error: { message: "Cannot deactivate or demote the final administrator" } } } });
    renderPage("/management?tab=users");
    fireEvent.click(await screen.findByLabelText("Edit Ian Instructor"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText("Account active"));
    fireEvent.click(within(dialog).getByText("Save changes"));
    fireEvent.click(within(await screen.findByText("Confirm access change").then((el) => el.closest("[role=dialog]") as HTMLElement)).getByText("Apply change"));
    expect(await screen.findByText("Cannot deactivate or demote the final administrator")).toBeTruthy();
  });

  it("shows empty, error-with-retry and forbidden states", async () => {
    mockApi({ users: [], userTotal: "0" }); renderPage("/management?tab=users");
    expect(await screen.findByText("No users match")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    mockApi({ failures: { "/v1/users": { response: { status: 500, data: { error: { message: "Users backend down", request_id: "r5" } } } } } }); renderPage("/management?tab=users");
    expect(await screen.findByText("Users backend down")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    mockApi({ failures: { "/v1/users": { response: { status: 403, data: {} } } } }); renderPage("/management?tab=users");
    expect(await screen.findByText("Only administrators can manage users")).toBeTruthy();
  });
});

describe("Courses and classrooms", () => {
  it("creates a course with the chosen classroom and saves edits", async () => {
    mockApi(); post.mockResolvedValue({ data: { id: 5 } } as any); put.mockResolvedValue({ data: { id: 3 } } as any);
    renderPage();
    fireEvent.click(await screen.findByText("Add course"));
    let dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Code"), { target: { value: "MATH200" } });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Calculus" } });
    fireEvent.change(within(dialog).getByLabelText("Classroom"), { target: { value: "1" } });
    fireEvent.click(within(dialog).getByText("Save course"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/courses", { code: "MATH200", name: "Calculus", description: null, academic_term: null, classroom_id: 1 }));
    fireEvent.click(await screen.findByLabelText("Edit CS101"));
    dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText("Course active"));
    fireEvent.click(within(dialog).getByText("Save course"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/v1/courses/3", expect.objectContaining({ code: "CS101", active: false })));
  });

  it("manages course members: an administrator picks a user, an instructor types an ID; removal is confirmed", async () => {
    mockApi(); post.mockResolvedValue({ data: {} } as any); del.mockResolvedValue({ data: {} } as any);
    renderPage();
    fireEvent.click(await screen.findByLabelText("Members of CS101"));
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("Ian Instructor")).toBeTruthy();
    fireEvent.change(within(drawer).getByLabelText("User"), { target: { value: "1" } });
    fireEvent.change(within(drawer).getByLabelText("Membership role"), { target: { value: "REVIEWER" } });
    fireEvent.click(within(drawer).getByText("Add / update member"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/courses/3/members", { user_id: 1, membership_role: "REVIEWER" }));
    fireEvent.click(within(drawer).getByLabelText("Remove Ian Instructor"));
    expect(del).not.toHaveBeenCalled();
    const confirm = (await screen.findByText("Remove this member?")).closest("[role=dialog]") as HTMLElement;
    fireEvent.click(within(confirm).getByText("Remove member"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/v1/courses/3/members/2"));
    cleanup(); vi.resetAllMocks(); mockApi({ role: "INSTRUCTOR" });
    renderPage();
    fireEvent.click(await screen.findByLabelText("Members of CS101"));
    expect(await screen.findByLabelText("User ID")).toBeTruthy();
    expect(usersCalls().length).toBe(0);
  });

  it("assigns only unassigned sessions to a course (session ownership)", async () => {
    mockApi(); post.mockResolvedValue({ data: {} } as any);
    renderPage();
    fireEvent.click(await screen.findByLabelText("Sessions of CS101"));
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("Assigned lecture")).toBeTruthy();
    const options = within(within(drawer).getByLabelText("Assign an unassigned session")).getAllByRole("option").map((option) => option.textContent);
    expect(options).toContain("Unassigned lecture (#20)");
    expect(options.join()).not.toContain("Already assigned");
    fireEvent.change(within(drawer).getByLabelText("Assign an unassigned session"), { target: { value: "20" } });
    fireEvent.click(within(drawer).getByText("Assign to course"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/courses/3/sessions", { session_id: 20 }));
  });

  it("creates and edits classrooms and confirms archiving", async () => {
    mockApi(); post.mockResolvedValue({ data: {} } as any); put.mockResolvedValue({ data: {} } as any);
    renderPage("/management?tab=classrooms");
    fireEvent.click(await screen.findByText("Add classroom"));
    let dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Lab 3" } });
    fireEvent.click(within(dialog).getByText("Save classroom"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/classrooms", expect.objectContaining({ name: "Lab 3", total_seats: 40 })));
    fireEvent.click(await screen.findByLabelText("Edit Room 204"));
    dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Seat capacity"), { target: { value: "45" } });
    fireEvent.click(within(dialog).getByText("Save classroom"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/v1/classrooms/1", expect.objectContaining({ total_seats: 45 })));
    fireEvent.click(await screen.findByText("Archive…"));
    expect(post).toHaveBeenCalledTimes(1);
    const confirm = (await screen.findByText("Archive this classroom?")).closest("[role=dialog]") as HTMLElement;
    expect(within(confirm).getByText(/Existing sessions, layouts and reports are kept/)).toBeTruthy();
    fireEvent.click(within(confirm).getByText("Archive"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/classrooms/1/archive", null, { params: { restore: false } }));
  });

  it("shows loading, empty and error states with retry for courses", async () => {
    let resolve: (value: any) => void = () => {};
    get.mockImplementation((url: any) => {
      const u = String(url);
      if (u.includes("/v1/auth/me")) return Promise.resolve({ data: { id: 1, role: "ADMINISTRATOR", auth_enabled: true } }) as any;
      if (u === "/v1/courses") return new Promise((r) => { resolve = r; }) as any;
      return Promise.resolve({ data: [] }) as any;
    });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector(".skeleton-row")).toBeTruthy());
    resolve({ data: [] });
    expect(await screen.findByText("No courses")).toBeTruthy();
    cleanup(); vi.resetAllMocks();
    mockApi({ failures: { "/v1/courses": { response: { status: 500, data: { error: { message: "Courses backend down" } } } } } });
    renderPage();
    expect(await screen.findByText("Courses backend down")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });
});
