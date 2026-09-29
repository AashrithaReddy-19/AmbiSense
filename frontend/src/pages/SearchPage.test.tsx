// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../services/api";
import { EXAMPLE_QUERIES, SearchPage } from "./SearchPage";

vi.mock("../services/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const post = vi.mocked(api.post);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const sessionMatch = (overrides: Record<string, unknown> = {}) => ({ session_id: 7, session: "Chemistry lab", date: "2026-09-16T09:00:00", timestamp: null, metric: "session", value: "FAILED", status: "FAILED", activity_context: "LABORATORY", classroom_name: "Classroom A", coverage: 0.4, has_report: false, reason: "Matched because: Status is failed", confidence: null, ...overrides });
const response = (overrides: Record<string, unknown> = {}) => ({ data: { query: "Find failed processing jobs.", data_source: "REAL", match_kind: "EXPLICIT_FILTERS", matches: [sessionMatch()], applied_filters: [{ name: "status", description: "Status is failed" }, { name: "data_source", description: "Data source is REAL" }, { name: "access", description: "Only sessions you are authorized to view" }], not_applied: [], bounded: { limit: 100, returned: 1, truncated: false }, ...overrides } } as any);
const renderPage = (path = "/search") => render(<MemoryRouter initialEntries={[path]}><SearchPage /></MemoryRouter>);
const box = () => screen.getByLabelText("Your question") as HTMLInputElement;
const submit = (text: string) => { fireEvent.change(box(), { target: { value: text } }); fireEvent.click(screen.getByRole("button", { name: /^Search$/ })); };

describe("SearchPage", () => {
  it("shows the four required example questions and runs one when clicked", async () => {
    post.mockResolvedValue(response());
    renderPage();
    for (const example of ["Show completed lecture sessions from last week.", "Find sessions with low evidence coverage.", "Find failed processing jobs.", "Show reports from Classroom A."]) expect(EXAMPLE_QUERIES).toContain(example);
    fireEvent.click(screen.getByText("Find failed processing jobs."));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/search", { query: "Find failed processing jobs.", data_source: "REAL" }));
    expect(box().value).toBe("Find failed processing jobs.");
  });

  it("searches the REAL data source by default and can search another", async () => {
    post.mockResolvedValue(response());
    renderPage();
    expect((screen.getByLabelText("Data source") as HTMLSelectElement).value).toBe("REAL");
    fireEvent.change(screen.getByLabelText("Data source"), { target: { value: "TEST" } });
    submit("failed jobs");
    await waitFor(() => expect(post).toHaveBeenCalledWith("/search", { query: "failed jobs", data_source: "TEST" }));
  });

  it("disables Search for input shorter than two characters and explains why", () => {
    renderPage();
    fireEvent.change(box(), { target: { value: "a" } });
    expect((screen.getByRole("button", { name: /^Search$/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Enter at least two characters.")).toBeTruthy();
    expect(box().getAttribute("aria-invalid")).toBe("true");
    expect(post).not.toHaveBeenCalled();
  });

  it("explains only the filters the backend reports as applied, and lists the ones it did not apply", async () => {
    post.mockResolvedValue(response({ match_kind: "KEYWORD_METRIC", applied_filters: [{ name: "metric", description: "Metric is engagement score (stored per-interval snapshot value)" }, { name: "threshold", description: "Value is below 50" }, { name: "data_source", description: "Data source is REAL" }], not_applied: [{ name: "date_range", description: "Date phrases are only supported for session searches" }] }));
    renderPage(); submit("engagement below 50 from last week");
    const section = (await screen.findByText("How your question was interpreted")).closest("section")!;
    expect(within(section).getByText("Keyword match")).toBeTruthy();
    expect(within(section).getByText("Value is below 50")).toBeTruthy();
    expect(within(section).queryByText(/Created last week/)).toBeNull(); // a date filter is never claimed when it was not applied
    expect(within(section).getByText(/Not applied:/)).toBeTruthy();
    expect(within(section).getByText(/Date phrases are only supported for session searches/)).toBeTruthy();
  });

  it("presents matches as a likely match with a reason, metadata and an open-session action", async () => {
    post.mockResolvedValue(response());
    renderPage(); submit("Find failed processing jobs.");
    const card = (await screen.findByText("Chemistry lab")).closest("li")!;
    expect(within(card).getByText("Likely match")).toBeTruthy();
    expect(within(card).getByText(/Matched because: Status is failed/)).toBeTruthy();
    expect(within(card).getByText(/Classroom A/)).toBeTruthy();
    expect(within(card).getByText(/Coverage 40%/)).toBeTruthy();
    expect(within(card).getByText("Open session").getAttribute("href")).toBe("/sessions/7");
  });

  it("never presents interpretation confidence as certainty", async () => {
    post.mockResolvedValue(response({ match_kind: "SEMANTIC_METRIC", matches: [sessionMatch({ metric: "engagement_score", value: 32.5, timestamp: 12, confidence: 0.62, reason: "engagement score was 32.5 at 12.0s" })] }));
    renderPage(); submit("how lively was the room");
    expect(await screen.findByText("Semantic suggestion (approximate)")).toBeTruthy();
    expect(screen.getByText(/Interpretation confidence 62% — how well the question matched this metric, not a guarantee/)).toBeTruthy();
    expect(screen.getAllByText(/at 12\.0s/).length).toBeGreaterThan(0);
    expect(screen.getByText("Open session").getAttribute("href")).toBe("/sessions/7?tab=timeline");
    expect(document.body.textContent).not.toMatch(/certain|guaranteed accurate|definitely/i);
  });

  it("groups many hits from one session into one card with a short moments list", async () => {
    const hits = Array.from({ length: 6 }, (_, index) => sessionMatch({ metric: "distracted_students", value: 12 + index, timestamp: index * 5, reason: `distracted students was ${12 + index} at ${index * 5}.0s`, confidence: 1 }));
    post.mockResolvedValue(response({ match_kind: "KEYWORD_METRIC", matches: hits }));
    renderPage(); submit("more than 10 students were distracted");
    expect(await screen.findByText("1 matching session")).toBeTruthy();
    expect(screen.getByText(/and 3 more moments in this session/)).toBeTruthy();
  });

  it("paginates a bounded result set and says when the bound was reached", async () => {
    const matches = Array.from({ length: 25 }, (_, index) => sessionMatch({ session_id: 100 + index, session: `Session ${index}` }));
    post.mockResolvedValue(response({ matches, bounded: { limit: 100, returned: 25, truncated: true } }));
    renderPage(); submit("stopped sessions");
    expect(await screen.findByText("25 matching sessions")).toBeTruthy();
    expect(screen.getByText(/Only the first 100 matches are searched and shown/)).toBeTruthy();
    expect(screen.getAllByRole("listitem").filter((item) => item.classList.contains("match-card")).length).toBe(10);
    fireEvent.click(screen.getByLabelText("Next page"));
    expect(await screen.findByText("Session 10")).toBeTruthy();
  });

  it("shows an insufficient-query state when the backend recognised no filter", async () => {
    post.mockResolvedValue(response({ matches: [sessionMatch()], applied_filters: [{ name: "data_source", description: "Data source is REAL" }], not_applied: [{ name: "query", description: "No supported session filter was recognised" }] }));
    renderPage(); submit("show me my sessions please");
    expect(await screen.findByText("Your question was not specific enough")).toBeTruthy();
    expect(screen.queryByText("Chemistry lab")).toBeNull();
  });

  it("shows an empty state, an error with retry, and an unauthorized state", async () => {
    post.mockResolvedValueOnce(response({ matches: [] }));
    renderPage(); submit("failed jobs");
    expect(await screen.findByText("No matching sessions")).toBeTruthy();
    post.mockRejectedValueOnce({ response: { status: 500, data: { error: { message: "Search backend down", request_id: "req-7" } } } });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/ }));
    expect(await screen.findByText("Search backend down")).toBeTruthy();
    post.mockResolvedValueOnce(response());
    fireEvent.click(screen.getByText("Retry"));
    expect(await screen.findByText("Chemistry lab")).toBeTruthy();
    post.mockRejectedValueOnce({ response: { status: 403, data: {} } });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/ }));
    expect(await screen.findByText("You are not authorized to search this data")).toBeTruthy();
  });

  it("shows a loading state while searching and only the newest submission wins", async () => {
    let resolveFirst: (value: any) => void = () => {};
    post.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }) as any);
    const { container } = renderPage(); submit("first question");
    expect(container.querySelector(".skeleton-row")).toBeTruthy();
    post.mockResolvedValueOnce(response({ matches: [sessionMatch({ session: "Newest result" })] }));
    fireEvent.click(screen.getByText("Find failed processing jobs.")); // an example can be chosen while the first search is still running
    expect(await screen.findByText("Newest result")).toBeTruthy();
    await act(async () => { resolveFirst(response({ matches: [sessionMatch({ session: "Stale result" })] })); });
    expect(screen.queryByText("Stale result")).toBeNull();
  });

  it("clears the question, the results and the URL", async () => {
    post.mockResolvedValue(response());
    renderPage("/search?q=failed%20jobs");
    expect(await screen.findByText("Chemistry lab")).toBeTruthy(); // a shared link runs once on load
    fireEvent.click(screen.getByText("Clear"));
    expect(box().value).toBe("");
    expect(screen.queryByText("Chemistry lab")).toBeNull();
    expect(screen.getByText("Ask a question to begin")).toBeTruthy();
  });

  it("shows the privacy notice", () => {
    renderPage();
    expect(screen.getByText(/does not identify students/)).toBeTruthy();
  });
});
