// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { ToastProvider } from "../components/Toast";
import { api } from "../services/api";
import { ClassroomSetupPage } from "./ClassroomSetupPage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
const get = vi.mocked(api.get), post = vi.mocked(api.post), put = vi.mocked(api.put), del = vi.mocked(api.delete);
beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:reference"); URL.revokeObjectURL = vi.fn();
  // jsdom has no layout: give the canvas a 1000x600 box so client coordinates map 1:1 onto the 1000x600 world.
  Element.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 600, right: 1000, bottom: 600, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const square = (x: number, y: number, size = 0.2) => [{ x, y }, { x: x + size, y }, { x: x + size, y: y + size }, { x, y: y + size }];
const LAYOUT = (over: Record<string, unknown> = {}) => ({ id: 11, classroom_id: 1, name: "Layout 1", version: 2, active: true, reference_image_path: null, regions: [{ region_key: "front", name: "Front row", region_type: "SEAT", polygon: square(0.1, 0.1), active: true }, { region_key: "board", name: "Board", region_type: "PROJECTOR", polygon: square(0.6, 0.1), active: true }], ...over });
const ROOMS = [{ id: 1, name: "Room 204", description: "Main", location_label: "Block A", active: true, capacity: 40, expected_students: 35 }];

function mockApi({ rooms = ROOMS as any, layouts = [LAYOUT(), LAYOUT({ id: 10, version: 1, active: false, regions: [] })] as any, role = "ADMINISTRATOR", failRooms = null as any } = {}) {
  get.mockImplementation(async (url: any) => {
    const u = String(url);
    if (u.includes("/v1/auth/me")) return { data: { id: 1, email: "u@test", role, auth_enabled: true } } as any;
    if (u === "/v1/classrooms") { if (failRooms) throw failRooms; return { data: rooms } as any; }
    if (u.includes("/layouts")) return { data: layouts } as any;
    if (u.includes("/reference-image")) return { data: new Blob(["img"]) } as any;
    if (u.includes("/v1/sessions")) return { data: { items: [{ id: 9, name: "Retained video", analytics_mode: "REAL" }] } } as any;
    return { data: [] } as any;
  });
}
function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/classroom-setup"]}>
      <AuthProvider><ToastProvider>
        <Link to="/other">Leave to other page</Link>
        <Routes><Route path="/classroom-setup" element={<ClassroomSetupPage />} /><Route path="/other" element={<div>Other page</div>} /></Routes>
      </ToastProvider></AuthProvider>
    </MemoryRouter>,
  );
}
const canvas = () => screen.getByRole("application");
const click = (x: number, y: number) => fireEvent.pointerDown(canvas(), { clientX: x, clientY: y, pointerId: 1, button: 0 });
const drawSquare = (x0 = 300, y0 = 300, size = 120) => { for (const [x, y] of [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size]]) click(x, y); };
// The first render of the file pays the module-import cost, which is slow when the whole suite runs in parallel.
const loaded = () => screen.findByText("Regions (2)", undefined, { timeout: 5000 });
const regionBtn = (name: RegExp) => screen.getByRole("button", { name });
const saveButton = () => screen.getByText(/Save new version|Saving…/).closest("button") as HTMLButtonElement;


describe("ClassroomSetupPage loading and permissions", () => {
  it("shows loading, then the active layout's regions, capacity and version list", async () => {
    mockApi();
    const { container } = renderPage();
    expect(container.querySelector(".skeleton")).toBeTruthy();
    expect(await loaded()).toBeTruthy();
    expect(regionBtn(/Front row · Seat · 4 pts/)).toBeTruthy();
    expect(regionBtn(/Board · Projector \/ board · 4 pts/)).toBeTruthy();
    expect(screen.getByText("from version 2")).toBeTruthy();
    const versions = screen.getByRole("table", { name: /Saved layout versions/ });
    expect(within(versions).getByText("v2")).toBeTruthy();
    expect(within(versions).getByText("Active")).toBeTruthy();
    expect(within(versions).getByText("Inactive")).toBeTruthy();
    expect(screen.getByRole("option", { name: "Room 204 · capacity 40" })).toBeTruthy();
  });

  it("fetches the reference image with the authenticated client and shows it on the canvas", async () => {
    mockApi(); renderPage();
    await loaded();
    expect(get).toHaveBeenCalledWith("/v1/classrooms/1/reference-image", { responseType: "blob" });
    await waitFor(() => expect(canvas().querySelector("image")?.getAttribute("href")).toBe("blob:reference"));
  });

  it("shows an empty state (and a create action for editors) when there are no classrooms", async () => {
    mockApi({ rooms: [] }); renderPage();
    expect(await screen.findByText("No classrooms yet")).toBeTruthy();
    expect(screen.getByText("Create classroom")).toBeTruthy();
    cleanup(); vi.resetAllMocks(); mockApi({ rooms: [], role: "VIEWER" }); renderPage();
    expect(await screen.findByText("An administrator or instructor must create a classroom first.")).toBeTruthy();
  });

  it("shows an error with retry when classrooms cannot be loaded", async () => {
    mockApi({ failRooms: { response: { status: 500, data: { error: { message: "Classrooms backend down", request_id: "r1" } } } } });
    renderPage();
    expect(await screen.findByText("Classrooms backend down")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("gives viewers a read-only editor: no Draw tool, no Save, no delete or archive actions", async () => {
    mockApi({ role: "VIEWER" }); renderPage();
    await loaded();
    await waitFor(() => expect(screen.getByText("Your role can view layouts but not change them.")).toBeTruthy());
    expect(screen.queryByText("Draw")).toBeNull();
    expect(screen.queryByText("Save new version")).toBeNull();
    expect(screen.queryByText("New classroom")).toBeNull();
    expect(screen.queryByText("Deactivate…")).toBeNull();
    expect(screen.getByText("Select / edit")).toBeTruthy();
    expect(screen.getByText("Pan")).toBeTruthy();
  });
});

describe("drawing and validation", () => {
  it("draws a polygon with the pointer, finishes it, and saves a new version with normalized coordinates", async () => {
    mockApi(); post.mockResolvedValue({ data: { ...LAYOUT({ id: 12, version: 3 }), regions: [{ region_key: "new", name: "Seat 01", region_type: "SEAT", polygon: square(0.3, 0.5), active: true }], warnings: [] } } as any);
    renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Draw"));
    drawSquare(300, 300, 120);
    fireEvent.click(screen.getByText("Finish polygon"));
    expect(await screen.findByText("Regions (3)")).toBeTruthy();
    expect(screen.getByText(/Unsaved changes\./)).toBeTruthy();
    expect(saveButton().disabled).toBe(false);
    fireEvent.click(saveButton());
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [url, body] = post.mock.calls[0] as any;
    expect(url).toBe("/v1/classrooms/1/layouts");
    expect(body.regions).toHaveLength(3);
    expect(body.regions[2]).toMatchObject({ name: "Seat 01", region_type: "SEAT", active: true, polygon: [{ x: 0.3, y: 0.5 }, { x: 0.42, y: 0.5 }, { x: 0.42, y: 0.7 }, { x: 0.3, y: 0.7 }] });
    expect(await screen.findByText(/Saved layout version 3\./)).toBeTruthy();
    await waitFor(() => expect(screen.queryByText(/Unsaved changes\./)).toBeNull());
  });

  it("rejects a self-intersecting (bow-tie) drawing with an explanation and adds no region", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Draw"));
    for (const [x, y] of [[100, 100], [500, 500], [500, 100], [100, 500]]) click(x, y);
    fireEvent.click(screen.getByText("Finish polygon"));
    expect(await screen.findByText("Polygon edges cross each other; reorder or move the points.")).toBeTruthy();
    expect(screen.getByText("Regions (2)")).toBeTruthy();
  });

  it("requires at least three points before a polygon can be finished, and Escape cancels drawing", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Draw"));
    click(200, 200); click(300, 200);
    expect((screen.getByText("Finish polygon") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(canvas(), { key: "Escape" });
    expect((screen.getByText("Cancel") as HTMLButtonElement).disabled).toBe(true);
  });

  it("finishes with Enter and removes the last point with Backspace (keyboard drawing)", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Draw"));
    drawSquare(300, 300, 100); click(700, 500);
    fireEvent.keyDown(canvas(), { key: "Backspace" });
    fireEvent.keyDown(canvas(), { key: "Enter" });
    expect(await screen.findByText("Regions (3)")).toBeTruthy();
  });

  it("blocks saving while a polygon is invalid and lists the problem, but only warns about overlaps", async () => {
    mockApi({ layouts: [LAYOUT({ regions: [{ region_key: "bad", name: "Bowtie", region_type: "SEAT", polygon: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }, { x: 0.5, y: 0.1 }, { x: 0.1, y: 0.5 }], active: true }, { region_key: "a", name: "A", region_type: "SEAT", polygon: square(0.6, 0.6), active: true }, { region_key: "b", name: "B", region_type: "ZONE", polygon: square(0.65, 0.65), active: true }] })] });
    renderPage();
    await screen.findByText("Regions (3)");
    const validation = screen.getByRole("heading", { name: "Validation" }).closest("section")!;
    expect(within(validation).getByText(/“Bowtie”: Polygon edges cross each other/)).toBeTruthy();
    expect(within(validation).getByText(/“A” and “B” overlap/)).toBeTruthy();
    expect(within(validation).getByText("Fix before saving:")).toBeTruthy();
    expect(within(validation).getByText(/Overlap warnings \(saving is allowed\)/)).toBeTruthy();
    fireEvent.click(regionBtn(/Bowtie/));
    fireEvent.change(screen.getByLabelText("Selected region name"), { target: { value: "Bowtie renamed" } }); // make it dirty
    expect(saveButton().disabled).toBe(true);
  });

  it("shows the server's rejection when it refuses a layout", async () => {
    mockApi(); post.mockRejectedValue({ response: { status: 422, data: { error: { code: "INVALID_LAYOUT", message: "The layout contains invalid regions; nothing was saved.", details: [{ region_key: "x", code: "SELF_INTERSECTING", message: "Polygon edges cross each other; reorder the points." }] } } } });
    renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Draw"));
    drawSquare();
    fireEvent.click(screen.getByText("Finish polygon"));
    fireEvent.click(saveButton());
    expect(await screen.findByText("The server rejected the layout:")).toBeTruthy();
    expect(screen.getAllByText(/Polygon edges cross each other; reorder the points\./).length).toBeGreaterThan(0);
  });
});

describe("editing controls", () => {
  it("undoes and redoes structural edits", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Draw"));
    drawSquare(); fireEvent.click(screen.getByText("Finish polygon"));
    await screen.findByText("Regions (3)");
    fireEvent.click(screen.getByLabelText("Undo"));
    expect(await screen.findByText("Regions (2)")).toBeTruthy();
    expect((screen.getByLabelText("Undo") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Redo"));
    expect(await screen.findByText("Regions (3)")).toBeTruthy();
    fireEvent.keyDown(window, { key: "z", ctrlKey: true }); // keyboard shortcut
    expect(await screen.findByText("Regions (2)")).toBeTruthy();
  });

  it("moves the selected region with the arrow keys (keyboard-accessible editing) and edits points numerically", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(regionBtn(/Front row · Seat/));
    const x0 = () => Number((screen.getByLabelText("Point 1 x") as HTMLInputElement).value);
    expect(x0()).toBeCloseTo(0.1);
    fireEvent.keyDown(canvas(), { key: "ArrowRight" });
    await waitFor(() => expect(x0()).toBeCloseTo(0.105));
    fireEvent.keyDown(canvas(), { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(x0()).toBeCloseTo(0.125));
    const input = screen.getByLabelText("Point 1 y");
    fireEvent.change(input, { target: { value: "1.7" } });
    fireEvent.blur(input);
    await waitFor(() => expect(Number((screen.getByLabelText("Point 1 y") as HTMLInputElement).value)).toBe(1)); // clamped to the frame
  });

  it("renames a region and changes its type", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(regionBtn(/Front row · Seat/));
    fireEvent.change(screen.getByLabelText("Selected region name"), { target: { value: "Row A" } });
    fireEvent.change(screen.getByLabelText("Selected region type"), { target: { value: "ZONE" } });
    expect(await screen.findByRole("button", { name: /Row A · Zone · 4 pts/ })).toBeTruthy();
    expect(screen.getByText(/Unsaved changes\./)).toBeTruthy();
  });

  it("removes a polygon point but never below three points", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(regionBtn(/Front row · Seat/));
    fireEvent.click(screen.getByLabelText("Remove point 4"));
    expect(await screen.findByRole("button", { name: /Front row · Seat · 3 pts/ })).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Remove point 3"));
    expect(await screen.findByText(/A polygon must keep at least three points/)).toBeTruthy();
    expect(regionBtn(/Front row · Seat · 3 pts/)).toBeTruthy();
  });

  it("asks for confirmation before deleting a region, and Cancel keeps it", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(regionBtn(/Front row · Seat/));
    fireEvent.click(screen.getByText("Delete region…"));
    let dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/You can undo it, and nothing is saved until you save a new version/)).toBeTruthy();
    fireEvent.click(within(dialog).getByText("Cancel"));
    expect(screen.getByText("Regions (2)")).toBeTruthy();
    fireEvent.click(screen.getByText("Delete region…"));
    dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByText("Delete region"));
    expect(await screen.findByText("Regions (1)")).toBeTruthy();
  });

  it("zooms in and out within limits and resets", async () => {
    mockApi(); renderPage();
    await loaded();
    expect(screen.getByLabelText("Reset zoom").textContent).toContain("100%");
    fireEvent.click(screen.getByLabelText("Zoom in"));
    expect(screen.getByLabelText("Reset zoom").textContent).toContain("125%");
    expect(canvas().getAttribute("viewBox")).not.toBe("0 0 1000 600");
    fireEvent.click(screen.getByLabelText("Reset zoom"));
    expect(canvas().getAttribute("viewBox")).toBe("0 0 1000 600");
    expect((screen.getByLabelText("Zoom out") as HTMLButtonElement).disabled).toBe(true);
    for (let i = 0; i < 12; i++) fireEvent.click(screen.getByLabelText("Zoom in"));
    expect((screen.getByLabelText("Zoom in") as HTMLButtonElement).disabled).toBe(true);
  });

  it("uses distinct stroke patterns per region type and lists them in a legend (not colour alone)", async () => {
    mockApi(); renderPage();
    await loaded();
    const legend = screen.getByLabelText("Legend");
    expect(within(legend).getByText("Seat")).toBeTruthy();
    expect(within(legend).getByText("Projector / board")).toBeTruthy();
    expect(within(legend).getByText("Invalid polygon")).toBeTruthy();
    const polygons = Array.from(canvas().querySelectorAll("polygon"));
    expect(polygons.map((p) => p.getAttribute("stroke-dasharray"))).toEqual([null, "12 4 2 4"]);
    expect(polygons[0].querySelector("title")?.textContent).toBe("Front row (Seat)");
  });
});

describe("unsaved changes and versions", () => {
  it("warns before an in-app link discards unsaved work; Stay keeps the editor, Leave navigates", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Draw"));
    drawSquare(); fireEvent.click(screen.getByText("Finish polygon"));
    await screen.findByText(/Unsaved changes\./);
    fireEvent.click(screen.getByText("Leave to other page"));
    let dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Leave without saving?")).toBeTruthy();
    fireEvent.click(within(dialog).getByText("Cancel"));
    expect(screen.queryByText("Other page")).toBeNull();
    expect(screen.getByText("Regions (3)")).toBeTruthy();
    fireEvent.click(screen.getByText("Leave to other page"));
    dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByText("Leave page"));
    expect(await screen.findByText("Other page")).toBeTruthy();
  });

  it("does not interrupt navigation when there are no unsaved changes", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Leave to other page"));
    expect(await screen.findByText("Other page")).toBeTruthy();
  });

  it("registers a beforeunload prompt only while there are unsaved changes", async () => {
    mockApi(); renderPage();
    await loaded();
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    fireEvent.click(screen.getByText("Draw"));
    drawSquare(); fireEvent.click(screen.getByText("Finish polygon"));
    await screen.findByText(/Unsaved changes\./);
    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);
  });

  it("loads an earlier version into the editor, asking first if there are unsaved changes", async () => {
    mockApi(); renderPage();
    await loaded();
    fireEvent.click(screen.getAllByText("Load into editor")[1]); // version 1 (no regions), nothing unsaved -> immediate
    expect(await screen.findByText("Regions (0)")).toBeTruthy();
    expect(screen.getByText("from version 1")).toBeTruthy();
    fireEvent.click(screen.getByText("Draw"));
    drawSquare(); fireEvent.click(screen.getByText("Finish polygon"));
    await screen.findByText(/Unsaved changes\./);
    fireEvent.click(screen.getAllByText("Load into editor")[0]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Discard unsaved changes?")).toBeTruthy();
    fireEvent.click(within(dialog).getByText("Discard and continue"));
    expect(await screen.findByText("Regions (2)")).toBeTruthy();
  });

  it("confirms before deactivating a version and then calls the API", async () => {
    mockApi(); del.mockResolvedValue({ data: { id: 11, active: false } } as any);
    renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Deactivate…"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Existing sessions and the saved version itself are kept/)).toBeTruthy();
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByText("Deactivate"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/v1/classrooms/1/layouts/11"));
    expect(await screen.findByText("Version 2 deactivated.")).toBeTruthy();
  });

  it("saving classroom details does not discard unsaved layout edits", async () => {
    mockApi(); put.mockResolvedValue({ data: { id: 1 } } as any);
    renderPage();
    await loaded();
    fireEvent.click(screen.getByText("Draw"));
    drawSquare(); fireEvent.click(screen.getByText("Finish polygon"));
    await screen.findByText("Regions (3)");
    fireEvent.click(screen.getByText("Classroom details and capacity"));
    fireEvent.change(screen.getByLabelText("Seat capacity"), { target: { value: "45" } });
    fireEvent.click(screen.getByText("Save classroom details"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/v1/classrooms/1", expect.objectContaining({ name: "Room 204", total_seats: 45 })));
    await waitFor(() => expect(screen.getByText("Classroom details saved.")).toBeTruthy());
    expect(screen.getByText("Regions (3)")).toBeTruthy(); // the drawn region is still there
  });

  it("disables New classroom while there are unsaved layout changes", async () => {
    mockApi(); renderPage();
    await loaded();
    expect((screen.getByText("New classroom").closest("button") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByText("Draw"));
    drawSquare(); fireEvent.click(screen.getByText("Finish polygon"));
    await screen.findByText(/Unsaved changes\./);
    expect((screen.getByText("New classroom").closest("button") as HTMLButtonElement).disabled).toBe(true);

  });
});
