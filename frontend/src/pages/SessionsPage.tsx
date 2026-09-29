/* eslint-disable react-hooks/set-state-in-effect -- session list synchronizes remote API state as filters/page change */
import { AlertCircle, Archive, GitCompare, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { useToast } from "../components/Toast";
import { api } from "../services/api";
import type { Session } from "../types";

const STATUSES = ["CREATED", "QUEUED", "INITIALIZING", "DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT", "COMPLETED", "FAILED", "STOPPED"];
const ACTIVITY_CONTEXTS = ["LECTURE", "EXAMINATION", "GROUP_DISCUSSION", "LABORATORY", "STUDENT_PRESENTATION", "INDEPENDENT_WRITING", "READING", "VIDEO_SCREENING", "BREAK"];

export function SessionsPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const { show } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [rows, setRows] = useState<Session[]>([]);
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [courses, setCourses] = useState<any[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [q, setQ] = useState(searchParams.get("q") || "");
  const [status, setStatus] = useState(searchParams.get("status") || "");
  const [mode, setMode] = useState(searchParams.get("mode") || "");
  const [classroomId, setClassroomId] = useState(searchParams.get("classroom_id") || "");
  const [courseId, setCourseId] = useState(searchParams.get("course_id") || "");
  const [activityContext, setActivityContext] = useState(searchParams.get("activity_context") || "");
  const [includeTests, setIncludeTests] = useState(searchParams.get("include_tests") === "1");
  const [archived, setArchived] = useState(searchParams.get("archived") === "1");
  const [startDate, setStartDate] = useState(searchParams.get("start_date") || "");
  const [endDate, setEndDate] = useState(searchParams.get("end_date") || "");
  const [minCoverage, setMinCoverage] = useState(searchParams.get("minimum_coverage") || "");
  const [page, setPage] = useState(Number(searchParams.get("page")) || 1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");

  // Validation feedback; the request is not sent while a filter is invalid.
  const dateError = startDate && endDate && startDate > endDate ? "End date must not be before the start date." : "";
  const coverageNumber = Number(minCoverage);
  const coverageError = minCoverage !== "" && (!Number.isFinite(coverageNumber) || coverageNumber < 0 || coverageNumber > 100) ? "Enter a percentage from 0 to 100." : "";
  const invalid = Boolean(dateError || coverageError);

  const load = useCallback(() => {
    let cancelled = false;
    if (invalid) { setLoading(false); return () => { cancelled = true; }; }
    setLoading(true); setError("");
    api
      .get("/v1/sessions", { params: { q: q || undefined, status: status || undefined, mode: mode || undefined, classroom_id: classroomId || undefined, course_id: courseId || undefined, activity_context: activityContext || undefined, start_date: startDate || undefined, end_date: endDate ? `${endDate}T23:59:59` : undefined, minimum_coverage: minCoverage !== "" ? coverageNumber / 100 : undefined, include_tests: includeTests, archived, page, page_size: 20 } })
      .then((r) => { if (cancelled) return; setRows(r.data.items); setPages(r.data.pages); setSelected([]); })
      .catch((e: any) => { if (cancelled) return; setError(e.response?.status === 403 ? "You are not authorized to view sessions." : e.response?.data?.detail?.error?.message || e.response?.data?.detail || "Sessions could not be loaded."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [q, status, mode, classroomId, courseId, activityContext, startDate, endDate, minCoverage, coverageNumber, invalid, includeTests, archived, page]);
  useEffect(() => load(), [load]);
  useEffect(() => {
    const next = new URLSearchParams();
    if (q) next.set("q", q); if (status) next.set("status", status); if (mode) next.set("mode", mode);
    if (classroomId) next.set("classroom_id", classroomId); if (courseId) next.set("course_id", courseId);
    if (activityContext) next.set("activity_context", activityContext); if (includeTests) next.set("include_tests", "1");
    if (archived) next.set("archived", "1"); if (page > 1) next.set("page", String(page));
    if (startDate) next.set("start_date", startDate); if (endDate) next.set("end_date", endDate); if (minCoverage !== "") next.set("minimum_coverage", minCoverage);
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, status, mode, classroomId, courseId, activityContext, startDate, endDate, minCoverage, includeTests, archived, page]);
  useEffect(() => {
    api.get("/v1/classrooms").then((r) => setClassrooms(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    api.get("/v1/courses").then((r) => setCourses(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  }, []);

  function toggle(id: number) {
    setSelected((old) => (old.includes(id) ? old.filter((value) => value !== id) : old.length >= 5 ? old : [...old, id]));
  }
  async function archiveOne(id: number) {
    try {
      await api.post(`/v1/sessions/${id}/archive`, null, { params: { archived: !archived } });
      show(archived ? "Session restored." : "Session archived.", "success");
      load();
    } catch (e: any) {
      show(e.response?.data?.detail || "That action could not be completed.", "error");
    }
  }
  async function bulk() {
    if (!selected.length || !confirm(`Archive ${selected.length} selected sessions? Active sessions will be skipped.`)) return;
    try {
      const r = await api.post("/v1/sessions/bulk-archive", { session_ids: selected });
      const summary = `Archived ${r.data.archived.length}; skipped ${r.data.skipped.length}; not found ${r.data.not_found.length}.`;
      setFeedback(summary);
      show(summary, r.data.skipped.length || r.data.not_found.length ? "warning" : "success");
      load();
    } catch (e: any) {
      const msg = e.response?.data?.detail || "Bulk archive failed.";
      setFeedback(msg); show(msg, "error");
    }
  }
  function resetFilters() {
    setQ(""); setStatus(""); setMode(""); setClassroomId(""); setCourseId(""); setActivityContext(""); setIncludeTests(false); setArchived(false); setStartDate(""); setEndDate(""); setMinCoverage(""); setPage(1);
    show("Filters reset.", "info");
  }
  const activeFilterCount = [q, status, mode, classroomId, courseId, activityContext, startDate, endDate, minCoverage].filter((value) => value !== "").length + (includeTests ? 1 : 0) + (archived ? 1 : 0);
  const classroomName = (id: number | null | undefined) => classrooms.find((c) => c.id === id)?.name;
  const courseName = (id: number | null | undefined) => { const c = courses.find((x) => x.id === id); return c ? c.code : undefined; };
  const all = rows.length > 0 && rows.every((row) => selected.includes(row.id));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Sessions</h1>
          <p>Searchable anonymous classroom history</p>
        </div>
        <div className="actions">
          {can("ADMINISTRATOR", "INSTRUCTOR") && (
            <button className="button secondary" disabled={!selected.length} onClick={bulk}>
              <Archive size={15} /> Archive selected ({selected.length})
            </button>
          )}
          <button className="button secondary" disabled={selected.length < 2 || selected.length > 5} title={selected.length < 2 ? "Select 2-5 sessions to compare" : undefined} onClick={() => navigate(`/compare?session_ids=${selected.join(",")}`)}>
            <GitCompare size={15} /> Compare selected ({selected.length})
          </button>
          {can("ADMINISTRATOR", "INSTRUCTOR") && <Link className="button" to="/upload">Upload video</Link>}
          {can("ADMINISTRATOR", "INSTRUCTOR") && <Link className="button secondary" to="/live">Start live</Link>}
        </div>
      </div>

      <div className="live-controls">
        <input aria-label="Search sessions" placeholder="Search sessions" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select aria-label="Status filter" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          {STATUSES.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}
        </select>
        <select aria-label="Classroom filter" value={classroomId} onChange={(e) => { setClassroomId(e.target.value); setPage(1); }}>
          <option value="">All classrooms</option>
          {classrooms.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select aria-label="Course filter" value={courseId} onChange={(e) => { setCourseId(e.target.value); setPage(1); }}>
          <option value="">All courses</option>
          {courses.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
        </select>
        <select aria-label="Activity context filter" value={activityContext} onChange={(e) => { setActivityContext(e.target.value); setPage(1); }}>
          <option value="">All activities</option>
          {ACTIVITY_CONTEXTS.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}
        </select>
        <select aria-label="Data source filter" value={mode} onChange={(e) => { setMode(e.target.value); setPage(1); }}>
          <option value="">Real and demo</option>
          <option value="REAL">Real only</option>
          <option value="DEMO">Demo only</option>
        </select>
        <label className="field"><span>Start date</span><input aria-label="Start date" type="date" value={startDate} onChange={(e) => { setStartDate(e.target.value); setPage(1); }} /></label>
        <label className="field"><span>End date</span><input aria-label="End date" type="date" value={endDate} aria-invalid={Boolean(dateError)} aria-describedby={dateError ? "sessions-date-error" : undefined} onChange={(e) => { setEndDate(e.target.value); setPage(1); }} /></label>
        <label className="field"><span>Minimum coverage (%)</span><input aria-label="Minimum coverage (%)" type="number" inputMode="decimal" min={0} max={100} step="any" placeholder="Any" value={minCoverage} aria-invalid={Boolean(coverageError)} aria-describedby={coverageError ? "sessions-coverage-error" : undefined} onChange={(e) => { setMinCoverage(e.target.value); setPage(1); }} /></label>
        <label className="toggle"><span>Include test sessions</span><input type="checkbox" checked={includeTests} onChange={(e) => { setIncludeTests(e.target.checked); setPage(1); }} /></label>
        <label className="toggle"><span>Archived</span><input type="checkbox" checked={archived} onChange={(e) => { setArchived(e.target.checked); setPage(1); }} /></label>
        {activeFilterCount > 0 && (
          <button type="button" className="button secondary" onClick={resetFilters}><RotateCcw size={14} /> Reset filters ({activeFilterCount})</button>
        )}
      </div>
      {dateError && <p className="field-error" id="sessions-date-error" role="alert">{dateError}</p>}
      {coverageError && <p className="field-error" id="sessions-coverage-error" role="alert">{coverageError}</p>}
      {invalid && <div className="notice error" role="status">Fix the highlighted filters to update the results.</div>}
      <p className="muted">Coverage is the share of a session's processed samples in which at least one person was detected. Filters run on the server and combine with pagination.</p>
      {feedback && <div className="notice">{feedback}</div>}

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading ? (
        <div className="table-card"><LoadingSkeleton kind="row" count={6} /></div>
      ) : (
        <section className="table-card">
          {rows.length ? (
            <table>
              <thead>
                <tr>
                  <th><input aria-label="Select filtered page (up to 5 for comparison)" type="checkbox" checked={all} onChange={() => setSelected(all ? [] : rows.filter((r) => !["PROCESSING", "INITIALIZING", "FINALIZING"].includes(r.status)).map((r) => r.id).slice(0, 5))} /></th>
                  <th>Session</th>
                  <th>Classroom</th>
                  <th>Course</th>
                  <th>Activity</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Date</th>
                  <th>Source</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} data-label={row.name}>
                    <td data-th=""><input type="checkbox" aria-label={`Select ${row.name} for comparison`} checked={selected.includes(row.id)} onChange={() => toggle(row.id)} /></td>
                    <td data-th="Session"><Link to={`/sessions/${row.id}`}>{row.name}</Link><small>#{row.id} · <b>{row.analytics_mode}</b>{row.is_test ? " · TEST" : ""}</small></td>
                    <td data-th="Classroom">{classroomName(row.classroom_id) || "Unassigned"}</td>
                    <td data-th="Course">{courseName(row.course_id) || "None"}</td>
                    <td data-th="Activity">{row.activity_context.replace(/_/g, " ")}</td>
                    <td data-th="Status"><StatusBadge status={row.status} />{row.stale ? <span className="badge badge-warning" title={row.stale_reason ?? undefined}><AlertCircle size={12} aria-hidden="true" />Stale</span> : null}<small>{row.stale ? "Not running: nothing is processing this session" : row.processing_stage.replace(/_/g, " ")}</small></td>
                    <td data-th="Progress">{row.progress}%<small>{row.processed_frames}/{row.total_frames}</small></td>
                    <td data-th="Date">{new Date(row.created_at).toLocaleDateString()}<small>{row.duration.toFixed(1)}s</small></td>
                    <td data-th="Source">{row.source_type}</td>
                    <td data-th="Action">
                      {can("ADMINISTRATOR", "INSTRUCTOR") && (
                        <button className="secondary" onClick={() => void archiveOne(row.id)}>
                          <Archive size={14} /> {archived ? "Restore" : "Archive"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState
              title={activeFilterCount > 0 ? "No sessions match these filters" : "No sessions found"}
              description={activeFilterCount > 0 ? "Try removing a filter." : can("ADMINISTRATOR", "INSTRUCTOR") ? "Upload a video or start a live session to begin." : "No sessions are available to you yet."}
              action={activeFilterCount > 0 ? <button className="button secondary" onClick={resetFilters}>Reset filters</button> : can("ADMINISTRATOR", "INSTRUCTOR") ? <Link className="button" to="/upload">Upload video</Link> : undefined}
            />
          )}
        </section>
      )}
      <div className="actions">
        <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
        <span>Page {page} of {pages}</span>
        <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</button>
      </div>
    </>
  );
}
