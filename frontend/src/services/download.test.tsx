// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { downloadFile, filenameFromDisposition, useInFlight } from "./download";

vi.mock("./api", () => ({ api: { get: vi.fn() } }));
const get = vi.mocked(api.get);
beforeEach(() => { URL.createObjectURL = vi.fn(() => "blob:test"); URL.revokeObjectURL = vi.fn(); });
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("filenameFromDisposition", () => {
  it("reads plain, quoted and RFC 5987 names and falls back safely", () => {
    expect(filenameFromDisposition('attachment; filename="session_4.pdf"', "x")).toBe("session_4.pdf");
    expect(filenameFromDisposition("attachment; filename=report.csv", "x")).toBe("report.csv");
    expect(filenameFromDisposition("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.csv", "x")).toBe("résumé.csv");
    expect(filenameFromDisposition(undefined, "fallback.pdf")).toBe("fallback.pdf");
  });
});

describe("downloadFile", () => {
  it("fetches through the authenticated client without the /api prefix and saves a blob", async () => {
    get.mockResolvedValue({ data: new Blob(["x"]), headers: { "content-disposition": 'attachment; filename="session_4.pdf"' } } as any);
    const click = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(click);
    const name = await downloadFile("/api/sessions/4/report?format=pdf", "fallback.pdf");
    expect(get).toHaveBeenCalledWith("/sessions/4/report?format=pdf", { responseType: "blob" });
    expect(name).toBe("session_4.pdf");
    expect(click).toHaveBeenCalledTimes(1);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("decodes a JSON error body that axios delivered as a Blob so the real message can be shown", async () => {
    const failure = { response: { status: 409, data: new Blob([JSON.stringify({ error: { code: "CONFLICT", message: "Report is unavailable until processing completes" } })]) } };
    get.mockRejectedValue(failure);
    await expect(downloadFile("/sessions/9/report?format=pdf", "x.pdf")).rejects.toBe(failure);
    expect((failure.response.data as any).error.message).toBe("Report is unavailable until processing completes");
  });

  it("survives an unreadable error body", async () => {
    const failure = { response: { status: 500, data: new Blob(["<html>oops</html>"]) } };
    get.mockRejectedValue(failure);
    await expect(downloadFile("/x", "x")).rejects.toBe(failure);
    expect(failure.response.data).toEqual({});
  });
});

describe("useInFlight", () => {
  it("ignores a second call with the same key while the first runs, and allows different keys", async () => {
    const { result } = renderHook(() => useInFlight());
    let finish: () => void = () => {};
    const task = vi.fn(() => new Promise<string>((resolve) => { finish = () => resolve("done"); }));
    let first: Promise<string | undefined> = Promise.resolve(undefined);
    act(() => { first = result.current.run("a", task); });
    expect(result.current.busy("a")).toBe(true);
    let second: string | undefined = "unset";
    await act(async () => { second = await result.current.run("a", task); });
    expect(second).toBeUndefined();
    expect(task).toHaveBeenCalledTimes(1);
    const other = vi.fn(async () => "other");
    await act(async () => { await result.current.run("b", other); });
    expect(other).toHaveBeenCalledTimes(1);
    await act(async () => { finish(); await first; });
    expect(result.current.busy("a")).toBe(false);
    await act(async () => { await result.current.run("a", async () => "again"); });
    expect(task).toHaveBeenCalledTimes(1); // released, and a new call is allowed
  });

  it("releases the key even when the task throws", async () => {
    const { result } = renderHook(() => useInFlight());
    await act(async () => { await expect(result.current.run("a", async () => { throw new Error("boom"); })).rejects.toThrow("boom"); });
    expect(result.current.busy("a")).toBe(false);
  });
});


