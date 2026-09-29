/* eslint-disable react-hooks/set-state-in-effect -- a shared link with ?q= runs its search once on load */
import { Search as SearchIcon, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Pagination } from "../components/Pagination";
import { PrivacyNotice } from "../components/PrivacyNotice";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { DATA_SOURCES, METRIC_LABELS, apiProblem, contextLabel, formatDateTime, isForbidden, percent, type ApiProblem } from "../constants";
import { api } from "../services/api";

export const EXAMPLE_QUERIES = [
  "Show completed lecture sessions from last week.",
  "Find sessions with low evidence coverage.",
  "Find failed processing jobs.",
  "Show reports from Classroom A.",
  "Show when more than 10 students were distracted",
];
const PAGE_SIZE = 10;
const MAX_MOMENTS = 3;
const KIND_TEXT: Record<string, string> = {
  EXPLICIT_FILTERS: "Explicit filters",
  TEXT_MATCH: "Text match",
  KEYWORD_METRIC: "Keyword match",
  SEMANTIC_METRIC: "Semantic suggestion (approximate)",
};
const RAW_METRIC_LABELS: Record<string, string> = {
  distracted_students: "Students with off-forward visual orientation", occupancy_rate: "Anonymous occupancy rate", engagement_score: "Observable participation indicator", attention_score: "Visual-orientation estimate",
  fatigue_score: "Possible fatigue indicator", drowsiness_count: "Possible prolonged eye closure", yawning_count: "Yawning observations", raised_hands: "Raised-hand observations",
  looking_down_students: "Students looking down", looking_away_students: "Students looking away", session: "Session", transcript: "Transcript", camera_quality: "Camera quality",
};

type Match = { session_id: number; session: string; date?: string; timestamp: number | null; metric: string; value: unknown; reason: string; confidence: number | null; status?: string; activity_context?: string; classroom_name?: string | null; coverage?: number | null; has_report?: boolean; source_type?: string };
type SearchResult = { query: string; data_source: string; matches: Match[]; applied_filters: Array<{ name: string; description: string }>; not_applied: Array<{ name: string; description: string }>; match_kind?: string; bounded?: { limit: number; returned: number; truncated: boolean }; interpreted_filter?: Record<string, any> };

function valueText(match: Match): string {
  if (match.metric === "session") return String(match.value).replace(/_/g, " ").toLowerCase();
  if (typeof match.value === "number") return Number.isInteger(match.value) ? String(match.value) : match.value.toFixed(1);
  return String(match.value ?? "");
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [source, setSource] = useState(params.get("source") ?? "REAL");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error" | "forbidden">("idle");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [page, setPage] = useState(1);
  const latest = useRef(0);
  const trimmed = query.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < 2;

  const run = useCallback(async (text: string, dataSource: string) => {
    const ticket = ++latest.current; // only the most recent submission may update the screen
    setState("loading"); setProblem(null); setPage(1);
    try {
      const response = await api.post("/search", { query: text, data_source: dataSource });
      if (ticket !== latest.current) return;
      setResult(response.data); setState("ok");
    } catch (error) {
      if (ticket !== latest.current) return;
      const failure = apiProblem(error, "The search could not be completed.");
      setProblem(failure); setState(isForbidden(failure) ? "forbidden" : "error");
    }
  }, []);

  // A shared or refreshed link with ?q= runs once on load.
  useEffect(() => {
    const initial = params.get("q");
    if (initial && initial.trim().length >= 2) void run(initial.trim(), params.get("source") ?? "REAL");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submit(event?: FormEvent, override?: string) {
    event?.preventDefault();
    const text = (override ?? query).trim();
    if (text.length < 2) return;
    if (override) setQuery(override);
    setParams({ q: text, ...(source !== "REAL" ? { source } : {}) }, { replace: true });
    void run(text, source);
  }
  function clear() {
    latest.current++;
    setQuery(""); setResult(null); setState("idle"); setProblem(null); setParams({}, { replace: true });
  }

  // One card per session; metric hits become a short list of moments instead of dozens of rows.
  const groups = useMemo(() => {
    const byId = new Map<number, { head: Match; moments: Match[] }>();
    for (const match of result?.matches ?? []) {
      const entry = byId.get(match.session_id) ?? { head: match, moments: [] };
      entry.moments.push(match);
      byId.set(match.session_id, entry);
    }
    return Array.from(byId.values());
  }, [result]);
  const pages = Math.max(1, Math.ceil(groups.length / PAGE_SIZE));
  const visible = groups.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const underspecified = state === "ok" && result?.not_applied?.some((item) => item.name === "query");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Search</h1>
          <p>Ask a question about stored, anonymous session evidence. Results are limited to sessions you are authorized to view.</p>
        </div>
      </div>
      <PrivacyNotice variant="compact" />

      <form className="filter-panel" onSubmit={submit} role="search" aria-label="Search stored analytics">
        <div className="field">
          <label htmlFor="search-question">Your question</label>
          <input id="search-question" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="For example: Find failed processing jobs" maxLength={500} aria-invalid={tooShort} aria-describedby={tooShort ? "search-short" : "search-help"} />
          {tooShort ? <p className="field-error" id="search-short" role="alert">Enter at least two characters.</p> : <p className="field-hint" id="search-help">Try a status, activity, date range, classroom, report or coverage level — or a metric threshold.</p>}
        </div>
        <div className="filter-grid" style={{ marginTop: 12 }}>
          <label className="field"><span>Data source</span>
            <select value={source} onChange={(event) => setSource(event.target.value)}>
              {DATA_SOURCES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </div>
        <div className="filter-actions">
          <button type="submit" className="button" disabled={trimmed.length < 2 || state === "loading"}><SearchIcon size={15} /> Search</button>
          <button type="button" className="button secondary" onClick={clear} disabled={!query && state === "idle"}><X size={14} /> Clear</button>
        </div>
      </form>

      <section aria-labelledby="examples-heading">
        <h2 id="examples-heading" className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>Example questions</h2>
        <ul className="example-list">
          {EXAMPLE_QUERIES.map((example) => <li key={example}><button type="button" className="button secondary small" onClick={() => submit(undefined, example)}>{example}</button></li>)}
        </ul>
      </section>

      <div aria-live="polite">
        {state === "loading" && <LoadingSkeleton kind="row" count={4} />}
        {state === "forbidden" && <EmptyState title="You are not authorized to search this data" description="Ask an administrator for access." />}
        {state === "error" && <ErrorState title="The search failed" message={problem?.message ?? "The search could not be completed."} code={problem?.requestId ?? problem?.code} onRetry={problem?.status === 400 ? undefined : () => void run(trimmed, source)} />}
        {state === "idle" && <EmptyState title="Ask a question to begin" description="Pick an example above or type your own." />}
      </div>

      {state === "ok" && result && (
        <>
          <section className="table-card" aria-labelledby="interpretation-heading">
            <h2 id="interpretation-heading">How your question was interpreted</h2>
            <p style={{ margin: "0 0 8px" }}><span className="badge badge-neutral">{KIND_TEXT[result.match_kind ?? ""] ?? "Interpreted"}</span></p>
            <ul style={{ margin: 0, paddingLeft: 18 }}>{result.applied_filters.map((filter) => <li key={`${filter.name}-${filter.description}`}>{filter.description}</li>)}</ul>
            {result.not_applied.length > 0 && (
              <div className="banner warning" style={{ marginTop: 12, marginBottom: 0 }} role="status">
                <div><b>Not applied:</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{result.not_applied.map((item) => <li key={item.name}>{item.description}</li>)}</ul></div>
              </div>
            )}
          </section>

          {underspecified ? (
            <EmptyState title="Your question was not specific enough" description="No supported filter was recognised. Try one of the example questions above, for example a status (failed, completed), an activity (lecture, examination), a date range (last week), a classroom or a coverage level." />
          ) : groups.length === 0 ? (
            <EmptyState title="No matching sessions" description="Nothing you are authorized to view matched these filters in the selected data source. Try another data source or a broader question." />
          ) : (
            <section aria-labelledby="results-heading">
              <h2 id="results-heading">{groups.length} matching session{groups.length === 1 ? "" : "s"}</h2>
              {result.bounded?.truncated && <div className="banner info" role="status">Only the first {result.bounded.limit} matches are searched and shown. Refine your question to narrow the results.</div>}
              <ul className="match-list">
                {visible.map(({ head, moments }) => {
                  const shown = moments.slice(0, MAX_MOMENTS);
                  return (
                    <li className="match-card" key={head.session_id}>
                      <h3>{head.session} <span className="badge badge-info">Likely match</span></h3>
                      <div className="muted">
                        {head.date ? formatDateTime(head.date) : null}{head.status ? <> · <StatusBadge status={head.status} /></> : null}
                        {head.classroom_name ? ` · ${head.classroom_name}` : ""}{head.activity_context ? ` · ${contextLabel(head.activity_context)}` : ""}
                        {head.coverage !== undefined && head.metric === "session" ? ` · Coverage ${percent(head.coverage)}` : ""}{head.has_report ? " · Report available" : ""}
                      </div>
                      {shown.map((match, index) => (
                        <div key={index}>
                          <div><b>Matched because:</b> {match.reason}</div>
                          {match.metric !== "session" && <div className="muted">{RAW_METRIC_LABELS[match.metric] ?? METRIC_LABELS[match.metric] ?? match.metric}: <b>{valueText(match)}</b>{match.timestamp != null ? ` at ${match.timestamp.toFixed(1)}s` : ""}</div>}
                          {match.confidence != null && <div className="muted">Interpretation confidence {Math.round(match.confidence * 100)}% — how well the question matched this metric, not a guarantee the result is correct.</div>}
                        </div>
                      ))}
                      {moments.length > shown.length && <div className="muted">and {moments.length - shown.length} more moment{moments.length - shown.length === 1 ? "" : "s"} in this session</div>}
                      <div><Link className="button secondary small" to={head.metric === "session" ? `/sessions/${head.session_id}` : `/sessions/${head.session_id}?tab=timeline`}>Open session</Link></div>
                    </li>
                  );
                })}
              </ul>
              <Pagination page={page} pages={pages} total={groups.length} noun="sessions" onPage={setPage} />
            </section>
          )}
        </>
      )}
    </>
  );
}
