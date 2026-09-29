/* eslint-disable react-hooks/set-state-in-effect -- the report list synchronizes remote API state with the applied filters and page */
import { Download, FileText, RefreshCw, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Dialog } from "../components/Dialog";
import { Pagination } from "../components/Pagination";
import { PrivacyNotice } from "../components/PrivacyNotice";
import { ReportDetails } from "../components/ReportDetails";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { ACTIVITY_CONTEXTS, DATA_SOURCES, apiProblem, contextLabel, formatDateTime, isForbidden, percent, type ApiProblem } from "../constants";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api } from "../services/api";
import { downloadFile, useInFlight } from "../services/download";
import { formatMetricAvailability } from "../components/MetricValue";

const DEFAULTS = { q: "", status: "", source_type: "", classroom: "", course: "", activity: "", source: "REAL", format: "", start: "", end: "" };
const STATUSES = ["COMPLETED", "PROCESSING", "QUEUED", "FAILED", "STOPPED"];
const FORMATS: Array<[string, string]> = [["pdf", "PDF"], ["csv", "CSV"], ["metrics", "Metrics CSV"]];
const FORMAT_LABEL: Record<string, string> = { pdf: "PDF", csv: "CSV", metrics: "Metrics CSV" };
const ACTIVE = new Set(["QUEUED", "DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT", "INITIALIZING", "FINALIZING"]);
const POLL_MS = 5000;

/** Never produces "—%" or "NaN%": a missing or non-finite progress is simply omitted. */
export function progressText(progress: number | null | undefined): string | null {
  return typeof progress === "number" && Number.isFinite(progress) ? `${Math.round(Math.max(0, Math.min(100, progress)))}%` : null;
}

export function ReportsPage() {
  const { applied, draft, update, apply, reset, activeCount, dirty, params, setExtra } = useUrlFilters(DEFAULTS);
  const { can } = useAuth();
  const { show } = useToast();
  const { run, busy } = useInFlight();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [response, setResponse] = useState<any | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "error" | "forbidden">("loading");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [courses, setCourses] = useState<any[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [details, setDetails] = useState<any | null>(null);
  const dateError = draft.start && draft.end && draft.start > draft.end ? "End date must not be before the start date." : "";

  useEffect(() => {
    Promise.all([api.get("/v1/classrooms").catch(() => ({ data: [] })), api.get("/v1/courses").catch(() => ({ data: [] }))])
      .then(([rooms, courseList]) => { setClassrooms(Array.isArray(rooms.data) ? rooms.data : []); setCourses(Array.isArray(courseList.data) ? courseList.data : []); });
  }, []);

  const load = useCallback((silent: boolean) => {
    let cancelled = false;
    if (!silent) { setState("loading"); setProblem(null); }
    api.get("/v1/reports", { params: {
      q: applied.q || undefined, status: applied.status || undefined, source_type: applied.source_type || undefined, classroom_id: applied.classroom || undefined, course_id: applied.course || undefined,
      activity_context: applied.activity || undefined, data_source: applied.source, format: applied.format || undefined,
      start_date: applied.start || undefined, end_date: applied.end ? `${applied.end}T23:59:59` : undefined, page, page_size: 20,
    } })
      .then((result) => { if (!cancelled) { setResponse(result.data); setState("ok"); } })
      .catch((error) => {
        if (cancelled) return;
        const failure = apiProblem(error, "Reports could not be loaded.");
        if (!silent) { setProblem(failure); setState(isForbidden(failure) ? "forbidden" : "error"); }
      });
    return () => { cancelled = true; };
  }, [applied, page]);
  useEffect(() => load(false), [load, reloadKey]);

  // Poll only while something on the page is still being processed; the interval is cleared otherwise and on unmount.
  const anyActive = (response?.items ?? []).some((row: any) => ACTIVE.has(row.status));
  useEffect(() => {
    if (!anyActive) return;
    let cancel: (() => void) | undefined;
    const id = window.setInterval(() => { cancel?.(); cancel = load(true); }, POLL_MS);
    return () => { window.clearInterval(id); cancel?.(); };
  }, [anyActive, load]);

  const classroomName = (id: number | null | undefined) => (id ? classrooms.find((room) => room.id === id)?.name ?? `Classroom #${id}` : "No classroom");
  const courseName = (id: number | null | undefined) => { if (!id) return "No course"; const course = courses.find((item) => item.id === id); return course ? `${course.code} · ${course.name}` : `Course #${id}`; };

  async function download(row: any, format: string) {
    const key = `${row.session_id}:${format}`;
    show(`Preparing ${FORMAT_LABEL[format]}…`, "info");
    await run(key, async () => {
      try { await downloadFile(`/sessions/${row.session_id}/report?format=${format}`, `session_${row.session_id}.${format === "pdf" ? "pdf" : "csv"}`); show(`${FORMAT_LABEL[format]} downloaded.`, "success"); }
      catch (error) { show(apiProblem(error, `${FORMAT_LABEL[format]} could not be downloaded.`).message, "error"); }
    });
  }
  async function retry(row: any) {
    await run(`retry:${row.session_id}`, async () => {
      try { await api.post(`/jobs/${row.job_id}/retry`); show("Processing was queued again.", "success"); setReloadKey((n) => n + 1); }
      catch (error) { show(apiProblem(error, "The job could not be retried.").message, "error"); }
    });
  }

  const items: any[] = response?.items ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <p>Generated reports for processed sessions, newest first. Downloads are enabled only for formats that exist.</p>
        </div>
      </div>
      <PrivacyNotice variant="compact" showValidation />

      <form className="filter-panel" aria-label="Report filters" onSubmit={(event) => { event.preventDefault(); if (!dateError) apply({}, ["page"]); }}>
        <h2>Filters {activeCount > 0 && <span className="count-pill">{activeCount} active</span>}</h2>
        <div className="filter-grid">
          <label className="field"><span>Search</span><input type="search" placeholder="Session or file name" value={draft.q} onChange={(e) => update("q", e.target.value)} /></label>
          <label className="field"><span>Status</span><select value={draft.status} onChange={(e) => update("status", e.target.value)}><option value="">All statuses</option>{STATUSES.map((v) => <option key={v} value={v}>{contextLabel(v)}</option>)}</select></label>
          <label className="field"><span>Source type</span><select value={draft.source_type} onChange={(e) => update("source_type", e.target.value)}><option value="">All sources</option><option value="VIDEO">Uploaded video</option><option value="LIVE">Live camera</option></select></label>
          <label className="field"><span>Classroom</span><select value={draft.classroom} onChange={(e) => update("classroom", e.target.value)}><option value="">All classrooms</option>{classrooms.map((room) => <option key={room.id} value={room.id}>{room.name}</option>)}</select></label>
          <label className="field"><span>Course</span><select value={draft.course} onChange={(e) => update("course", e.target.value)}><option value="">All courses</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.code}</option>)}</select></label>
          <label className="field"><span>Activity context</span><select value={draft.activity} onChange={(e) => update("activity", e.target.value)}><option value="">All activities</option>{ACTIVITY_CONTEXTS.map((v) => <option key={v} value={v}>{contextLabel(v)}</option>)}</select></label>
          <label className="field"><span>Data source</span><select value={draft.source} onChange={(e) => update("source", e.target.value)}>{DATA_SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}</select></label>
          <label className="field"><span>Format</span><select value={draft.format} onChange={(e) => update("format", e.target.value)}><option value="">Any format</option>{FORMATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="field"><span>Start date</span><input type="date" value={draft.start} onChange={(e) => update("start", e.target.value)} /></label>
          <div className="field"><label htmlFor="reports-end">End date</label><input id="reports-end" type="date" value={draft.end} aria-invalid={Boolean(dateError)} aria-describedby={dateError ? "reports-date-error" : undefined} onChange={(e) => update("end", e.target.value)} />{dateError && <p className="field-error" id="reports-date-error" role="alert">{dateError}</p>}</div>
        </div>
        <div className="filter-actions">
          <button type="submit" className="button" disabled={Boolean(dateError) || !dirty}>Apply filters</button>
          <button type="button" className="button secondary" disabled={activeCount === 0 && !dirty} onClick={() => reset(["page"])}><RotateCcw size={14} /> Reset</button>
          <button type="button" className="button ghost" onClick={() => setReloadKey((n) => n + 1)}><RefreshCw size={14} /> Refresh</button>
        </div>
      </form>

      {state === "loading" && <LoadingSkeleton kind="row" count={5} />}
      {state === "forbidden" && <EmptyState title="You are not authorized to view these reports" description="Reports are limited to sessions you can access." />}
      {state === "error" && <ErrorState message={problem?.message ?? "Reports could not be loaded."} code={problem?.requestId} onRetry={() => setReloadKey((n) => n + 1)} />}
      {state === "ok" && items.length === 0 && <EmptyState title="No reports match these filters" description="Process a video or relax the filters." action={activeCount > 0 ? <button className="button secondary" onClick={() => reset(["page"])}>Reset filters</button> : <Link className="button" to="/upload">Upload a video</Link>} />}

      {state === "ok" && items.length > 0 && (
        <section className="table-card table-scroll" aria-live="polite">
          <table className="data-table">
            <caption className="sr-only">Reports, newest first</caption>
            <thead><tr><th scope="col">Session</th><th scope="col">Status</th><th scope="col">Quality / coverage</th><th scope="col">Formats</th><th scope="col">Created</th><th scope="col">Actions</th></tr></thead>
            <tbody>
              {items.map((row) => {
                const formats: string[] = row.available_formats ?? [];
                const completed = row.status === "COMPLETED";
                const quality = row.metric_results?.frame_quality;
                const coverage = row.metric_results?.observable_participation?.coverage ?? row.metric_results?.occupancy?.coverage;
                const pct = progressText(row.progress);
                return (
                  <tr key={row.session_id}>
                    <th scope="row" data-th="Session">
                      <Link to={`/sessions/${row.session_id}`}>{row.name}</Link>
                      <small>{row.source_type === "LIVE" ? "Live session" : row.source_filename || "Uploaded video"} · {row.is_test ? "TEST" : row.analytics_mode}</small>
                      <small>{classroomName(row.classroom_id)} · {contextLabel(row.activity_context ?? "LECTURE")}</small>
                    </th>
                    <td data-th="Status">
                      <StatusBadge status={row.status} />
                      {!completed && ACTIVE.has(row.status) && pct && <small>{contextLabel(row.stage ?? row.status)} · {pct}</small>}
                      {row.status === "FAILED" && <small>{row.error ? String(row.error).slice(0, 120) : "Processing failed."}{row.failure_code ? ` (${row.failure_code})` : ""}</small>}
                    </td>
                    <td data-th="Quality / coverage">
                      <small style={{ color: "inherit" }}>{quality?.available ? formatMetricAvailability(quality) : "Frame quality unavailable"}</small>
                      <small>Coverage {percent(coverage)}</small>
                    </td>
                    <td data-th="Formats">{formats.length ? <ul className="chip-list">{formats.map((format) => <li className="chip" key={format}>{FORMAT_LABEL[format] ?? format}</li>)}</ul> : <span className="muted">None yet</span>}</td>
                    <td data-th="Created">{formatDateTime(row.created_at)}</td>
                    <td data-th="">
                      <div className="actions">
                        <button className="button secondary small" onClick={() => setDetails(row)}><FileText size={13} /> Details</button>
                        {FORMATS.map(([format, text]) => {
                          const ready = completed && formats.includes(format);
                          const inFlight = busy(`${row.session_id}:${format}`);
                          return <button key={format} className="button small" disabled={!ready || inFlight} aria-label={`Download ${text} for ${row.name}`} title={ready ? undefined : completed ? `${text} has not been generated` : "Available when processing completes"} onClick={() => void download(row, format)}><Download size={13} /> {inFlight ? "…" : text}</button>;
                        })}
                        {row.status === "FAILED" && row.job_id && can("ADMINISTRATOR", "INSTRUCTOR") && <button className="button secondary small" disabled={busy(`retry:${row.session_id}`)} onClick={() => void retry(row)}><RefreshCw size={13} /> Retry</button>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination page={response.page} pages={response.pages} total={response.total} noun="reports" onPage={(next) => setExtra("page", next === 1 ? null : String(next))} />
        </section>
      )}

      <Dialog open={Boolean(details)} title={details ? `Report details · ${details.name}` : "Report details"} variant="drawer" onClose={() => setDetails(null)}>
        {details && <ReportDetails report={details} classroomName={classroomName(details.classroom_id)} courseName={courseName(details.course_id)} />}
      </Dialog>
    </>
  );
}
