/* eslint-disable react-hooks/set-state-in-effect -- comparison and candidate lists synchronize remote API state as selection/filters change */
import { AlertTriangle, Download, Info, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMetricAvailability } from "../components/MetricValue";
import { PrivacyNotice } from "../components/PrivacyNotice";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { ACTIVITY_CONTEXTS, DATA_SOURCES, apiProblem, contextLabel, formatDuration, isForbidden, type ApiProblem } from "../constants";
import { api } from "../services/api";
import type { ComparisonResponse, MetricAvailability, Session } from "../types";

const METRIC_OPTIONS = [
  ["occupancy", "Anonymous occupancy estimate", "count"],
  ["peak_occupancy", "Peak anonymous occupancy estimate", "count"],
  ["unoccupied_capacity", "Estimated unoccupied capacity", "count"],
  ["visual_orientation", "Visual-orientation estimate", "percent"],
  ["observable_participation", "Observable participation indicator", "percent"],
  ["prolonged_eye_closure", "Possible prolonged eye closure", "count"],
  ["possible_fatigue", "Possible fatigue indicator", "percent"],
  ["yawning", "Yawning observations", "count"],
  ["raised_hands", "Raised-hand observations", "count"],
  ["frame_quality", "Frame-quality score", "percent"],
] as const;
const ALL_METRIC_NAMES = METRIC_OPTIONS.map(([key]) => key);
const METRIC_LABEL: Record<string, string> = Object.fromEntries(METRIC_OPTIONS.map(([k, l]) => [k, l]));
const METRIC_KIND: Record<string, "percent" | "count"> = Object.fromEntries(METRIC_OPTIONS.map(([k, , u]) => [k, u]));
const METRIC_NOUN: Record<string, string> = { occupancy: "people", peak_occupancy: "people", unoccupied_capacity: "seats", prolonged_eye_closure: "events", yawning: "events", raised_hands: "events" };
const PERCENT_METRICS = METRIC_OPTIONS.filter(([, , kind]) => kind === "percent").map(([key]) => key);
const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--primary)"];
const MAX_SESSIONS = 5;

export function parseSessionIds(raw: string | null): number[] {
  if (!raw) return [];
  const parsed = raw.split(",").map((v) => v.trim()).filter(Boolean).map(Number);
  if (parsed.some((v) => !Number.isInteger(v) || v <= 0)) return [];
  return Array.from(new Set(parsed)).slice(0, MAX_SESSIONS);
}

function CustomTooltip({ active, payload, kind }: { active?: boolean; payload?: any[]; kind: "percent" | "count" }) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  const contract: MetricAvailability | undefined = point?.__contract;
  if (!contract) return null;
  return (
    <div className="notice" style={{ maxWidth: 260, margin: 0 }}>
      <b>{point.name}</b>
      <p style={{ margin: "4px 0 0" }}>{formatMetricAvailability(contract, { kind })}</p>
      {contract.available && <p style={{ margin: "4px 0 0" }}>{contract.valid_observations} of {contract.total_observations} observations valid</p>}
    </div>
  );
}

/** One bar per session; a null value renders no bar (a gap), never a zero-height bar. */
function SessionBars({ data, name, color, domain, label }: { data: Array<{ name: string; value: number | null; __contract?: MetricAvailability }>; name: string; color: string; domain?: [number, number]; label: string }) {
  return (
    <div role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="name" stroke="var(--text-muted)" />
          <YAxis domain={domain} stroke="var(--text-muted)" />
          <Tooltip />
          <Legend />
          <Bar dataKey="value" name={name} fill={color} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

type RegionEvidence = { session_id: number; status?: string; layout_id?: number; layout_version?: number; regions?: Array<{ region_id: string; name: string; observation_count: number; estimated_unique_tracks: number; raised_hand_observations: number; visual_coverage: number | null }> };

export function SessionComparePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selected, setSelected] = useState<number[]>(() => parseSessionIds(searchParams.get("session_ids")));
  const [available, setAvailable] = useState<Session[]>([]);
  const [listState, setListState] = useState<"loading" | "ok" | "error">("loading");
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [courses, setCourses] = useState<any[]>([]);
  const [q, setQ] = useState(""), [classroomFilter, setClassroomFilter] = useState(""), [courseFilter, setCourseFilter] = useState(""), [activityFilter, setActivityFilter] = useState(""), [sourceFilter, setSourceFilter] = useState(""), [dataSource, setDataSource] = useState("REAL"), [startDate, setStartDate] = useState(""), [endDate, setEndDate] = useState("");
  const [metric, setMetric] = useState<string>("observable_participation");
  const [comparison, setComparison] = useState<ComparisonResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [regionEvidence, setRegionEvidence] = useState<RegionEvidence[]>([]);
  const dateError = startDate && endDate && startDate > endDate ? "End date must not be before the start date." : "";

  useEffect(() => {
    Promise.all([api.get("/v1/classrooms").catch(() => ({ data: [] })), api.get("/v1/courses").catch(() => ({ data: [] }))])
      .then(([rooms, courseList]) => { setClassrooms(Array.isArray(rooms.data) ? rooms.data : []); setCourses(Array.isArray(courseList.data) ? courseList.data : []); });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setListState("loading");
    api.get("/v1/sessions", { params: { status: "COMPLETED", page_size: 100, include_tests: dataSource === "TEST" || dataSource === "ALL" ? true : undefined, mode: dataSource === "REAL" || dataSource === "DEMO" ? dataSource : undefined } })
      .then((response) => {
        if (cancelled) return;
        const items: Session[] = response.data?.items || [];
        setAvailable(dataSource === "TEST" ? items.filter((row) => row.is_test) : items);
        setListState("ok");
      })
      .catch(() => { if (!cancelled) setListState("error"); });
    return () => { cancelled = true; };
  }, [dataSource]);

  useEffect(() => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      if (selected.length) next.set("session_ids", selected.join(",")); else next.delete("session_ids");
      return next;
    }, { replace: true });
  }, [selected, setSearchParams]);

  useEffect(() => {
    if (selected.length < 2) { setComparison(null); setProblem(null); setUnauthorized(false); setRegionEvidence([]); return; }
    let cancelled = false; // ignore a stale response when the selection changes again
    setLoading(true); setProblem(null); setUnauthorized(false);
    api.post("/v1/analytics/compare", { session_ids: selected, metrics: ALL_METRIC_NAMES })
      .then((response) => { if (!cancelled) setComparison(response.data); })
      .catch((error) => {
        if (cancelled) return;
        const failure = apiProblem(error, "Comparison could not be loaded.");
        if (isForbidden(failure)) setUnauthorized(true); else setProblem(failure);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selected, reloadKey]);

  // Region evidence is fetched only for a loaded comparison and is used only when layouts match (see below).
  useEffect(() => {
    if (!comparison) { setRegionEvidence([]); return; }
    let cancelled = false;
    Promise.all(comparison.sessions.map((row) => api.get(`/v1/sessions/${row.session_id}/regions`).then((response) => ({ session_id: row.session_id, ...(response.data ?? {}) }) as RegionEvidence).catch(() => ({ session_id: row.session_id, status: "UNAVAILABLE" }) as RegionEvidence)))
      .then((rows) => { if (!cancelled) setRegionEvidence(rows); });
    return () => { cancelled = true; };
  }, [comparison]);

  const classroomName = (id: number | null | undefined) => classrooms.find((c) => c.id === id)?.name || (id ? "Unknown classroom" : "No classroom");
  const courseName = (id: number | null | undefined) => { const c = courses.find((x) => x.id === id); return c ? `${c.code} · ${c.name}` : "No course"; };

  const filteredCandidates = useMemo(() => available.filter((row) => {
    if (selected.includes(row.id)) return false;
    if (q && !row.name.toLowerCase().includes(q.toLowerCase())) return false;
    if (classroomFilter && String(row.classroom_id || "") !== classroomFilter) return false;
    if (courseFilter && String(row.course_id || "") !== courseFilter) return false;
    if (activityFilter && row.activity_context !== activityFilter) return false;
    if (sourceFilter && row.source_type !== sourceFilter) return false;
    if (startDate && row.created_at.slice(0, 10) < startDate) return false;
    if (endDate && row.created_at.slice(0, 10) > endDate) return false;
    return true;
  }), [available, selected, q, classroomFilter, courseFilter, activityFilter, sourceFilter, startDate, endDate]);
  const activeFilters = [q, classroomFilter, courseFilter, activityFilter, sourceFilter, startDate, endDate].filter(Boolean).length + (dataSource !== "REAL" ? 1 : 0);
  function resetFilters() { setQ(""); setClassroomFilter(""); setCourseFilter(""); setActivityFilter(""); setSourceFilter(""); setStartDate(""); setEndDate(""); setDataSource("REAL"); }
  const addSession = (id: number) => setSelected((old) => (old.length < MAX_SESSIONS && !old.includes(id) ? [...old, id] : old));
  const removeSession = (id: number) => setSelected((old) => old.filter((value) => value !== id));

  const sessionRows = comparison?.sessions ?? [];
  const cell = (key: string, sessionId: number) => comparison?.metric_results[key]?.[String(sessionId)];
  const chartData = sessionRows.map((row) => { const contract = cell(metric, row.session_id); return { name: row.name, value: contract?.available ? contract.value : null, __contract: contract }; });
  const validData = sessionRows.map((row) => { const contract = cell(metric, row.session_id); return { name: row.name, value: contract ? contract.valid_observations : null }; });
  const coverageData = sessionRows.map((row) => ({ name: row.name, value: row.coverage != null ? Math.round(row.coverage * 100) : null }));
  const confidenceData = sessionRows.map((row) => ({ name: row.name, value: row.confidence != null ? Math.round(row.confidence * 100) : null }));
  const grouped = PERCENT_METRICS.map((key) => ({ metric: METRIC_LABEL[key], ...Object.fromEntries(sessionRows.map((row) => { const contract = cell(key, row.session_id); return [row.name, contract?.available ? contract.value : null]; })) }));
  const eventTypes = Array.from(new Set(sessionRows.flatMap((row) => Object.keys(row.event_counts ?? {})))).sort();
  const eventData = eventTypes.map((type) => ({ event: type.replace(/_/g, " "), ...Object.fromEntries(sessionRows.map((row) => [row.name, row.event_counts?.[type] ?? 0])) }));
  const notices = comparison?.compatibility.notices ?? [];
  const warningNotices = notices.filter((notice) => notice.level === "warning");
  const infoNotices = notices.filter((notice) => notice.level !== "warning");

  // Region comparison is honest only when every session was measured against the same calibrated layout version.
  const regionsComparable = regionEvidence.length === sessionRows.length && regionEvidence.length >= 2 && regionEvidence.every((row) => row.status === "CALIBRATED" && row.layout_id != null && row.layout_id === regionEvidence[0].layout_id);
  const regionKeys = regionsComparable ? Array.from(new Set(regionEvidence.flatMap((row) => (row.regions ?? []).map((region) => region.region_id)))) : [];
  const regionReason = regionEvidence.length === 0 ? "" : regionEvidence.some((row) => row.status !== "CALIBRATED") ? "at least one selected session has no calibrated classroom layout" : "the selected sessions used different classroom layouts, so regions are not aligned";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Compare sessions</h1>
          <p>Anonymous, observational evidence side by side. Not attendance, performance, or a causal conclusion.</p>
        </div>
        {comparison && (
          <div className="actions">
            <a className="button secondary" href={`/api/v1/analytics/compare/export?session_ids=${selected.join(",")}&metrics=${ALL_METRIC_NAMES.join(",")}`}>
              <Download size={16} />
              Export CSV
            </a>
          </div>
        )}
      </div>
      <PrivacyNotice variant="compact" />

      <section className="table-card" aria-labelledby="selected-heading">
        <h2 id="selected-heading">Selected sessions ({selected.length}/5)</h2>
        {selected.length === 0 ? (
          <div className="empty">Select at least two sessions below to compare.</div>
        ) : (
          <div className="summary-grid">
            {selected.map((id) => {
              const row = available.find((s) => s.id === id);
              const evidence = comparison?.sessions.find((s) => s.session_id === id);
              const results = evidence ? Object.values(evidence.metric_results) : [];
              const availableCount = results.filter((r) => r.available).length;
              return (
                <article key={id}>
                  <small>{row?.name || evidence?.name || `Session #${id}`}</small>
                  <b style={{ fontSize: 15 }}>{row ? classroomName(row.classroom_id) : evidence ? classroomName(evidence.classroom_id) : ""}</b>
                  <span>{row ? courseName(row.course_id) : ""}</span>
                  <span>{contextLabel((row?.activity_context ?? evidence?.context) || "")} · {row?.source_type ?? evidence?.source_type} · {row?.status ?? evidence?.status}</span>
                  <span>{row ? new Date(row.created_at).toLocaleDateString() : ""} · {formatDuration(row?.duration ?? evidence?.duration)}</span>
                  {evidence && <span>{availableCount} of {results.length} metrics available</span>}
                  <button className="button secondary small" onClick={() => removeSession(id)} aria-label={`Remove ${row?.name || evidence?.name || `session ${id}`}`}>
                    <X size={14} /> Remove
                  </button>
                </article>
              );
            })}
          </div>
        )}
        {selected.length > 0 && <button className="button secondary small" style={{ marginTop: 12 }} onClick={() => setSelected([])}>Clear all</button>}
      </section>

      <section className="table-card" aria-labelledby="add-heading">
        <h2 id="add-heading">Add sessions to compare {activeFilters > 0 && <span className="count-pill">{activeFilters} filter{activeFilters === 1 ? "" : "s"}</span>}</h2>
        <div className="filter-grid" role="search" aria-label="Filter sessions">
          <label className="field"><span>Search</span><input placeholder="Search sessions" value={q} onChange={(e) => setQ(e.target.value)} /></label>
          <label className="field"><span>Classroom</span>
            <select aria-label="Classroom filter" value={classroomFilter} onChange={(e) => setClassroomFilter(e.target.value)}>
              <option value="">All classrooms</option>{classrooms.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></label>
          <label className="field"><span>Course</span>
            <select aria-label="Course filter" value={courseFilter} onChange={(e) => setCourseFilter(e.target.value)}>
              <option value="">All courses</option>{courses.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
            </select></label>
          <label className="field"><span>Activity</span>
            <select aria-label="Activity filter" value={activityFilter} onChange={(e) => setActivityFilter(e.target.value)}>
              <option value="">All activities</option>{ACTIVITY_CONTEXTS.map((v) => <option key={v} value={v}>{contextLabel(v)}</option>)}
            </select></label>
          <label className="field"><span>Source</span>
            <select aria-label="Source filter" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
              <option value="">All sources</option><option value="VIDEO">Uploaded video</option><option value="LIVE">Live camera</option>
            </select></label>
          <label className="field"><span>Data source</span>
            <select aria-label="Data source filter" value={dataSource} onChange={(e) => setDataSource(e.target.value)}>
              {DATA_SOURCES.map((source) => <option key={source.value} value={source.value}>{source.label}</option>)}
            </select></label>
          <label className="field"><span>From</span><input aria-label="Start date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></label>
          <label className="field"><span>To</span>
            <input aria-label="End date" type="date" value={endDate} aria-invalid={Boolean(dateError)} aria-describedby={dateError ? "compare-date-error" : undefined} onChange={(e) => setEndDate(e.target.value)} />
            {dateError && <p className="field-error" id="compare-date-error" role="alert">{dateError}</p>}
          </label>
        </div>
        {activeFilters > 0 && <div className="filter-actions"><button className="button secondary small" onClick={resetFilters}><RotateCcw size={13} /> Reset filters</button></div>}
        {listState === "loading" ? <LoadingSkeleton kind="row" count={3} /> : listState === "error" ? (
          <ErrorState message="The session list could not be loaded." onRetry={() => setDataSource((value) => value)} />
        ) : filteredCandidates.length === 0 ? (
          <div className="empty">No completed sessions match these filters.</div>
        ) : (
          <table className="data-table">
            <caption className="sr-only">Completed sessions available to compare</caption>
            <thead><tr><th scope="col"><span className="sr-only">Action</span></th><th scope="col">Session</th><th scope="col">Classroom</th><th scope="col">Course</th><th scope="col">Activity</th><th scope="col">Source</th><th scope="col">Date</th></tr></thead>
            <tbody>
              {filteredCandidates.slice(0, 25).map((row) => (
                <tr key={row.id}>
                  <td data-th=""><button className="button small" disabled={selected.length >= MAX_SESSIONS} onClick={() => addSession(row.id)}>Add</button></td>
                  <th scope="row" data-th="Session">{row.name}</th>
                  <td data-th="Classroom">{classroomName(row.classroom_id)}</td>
                  <td data-th="Course">{courseName(row.course_id)}</td>
                  <td data-th="Activity">{contextLabel(row.activity_context)}</td>
                  <td data-th="Source">{row.source_type}</td>
                  <td data-th="Date">{new Date(row.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {filteredCandidates.length > 25 && <p className="muted">Showing the first 25 of {filteredCandidates.length} matching sessions; refine the filters to narrow the list.</p>}
        {selected.length >= MAX_SESSIONS && <p className="muted">The maximum of five sessions is selected. Remove one to add another.</p>}
      </section>

      {selected.length < 2 && <div className="notice">Select at least two sessions to run a comparison.</div>}
      {selected.length >= 2 && unauthorized && <div className="notice error" role="alert">You are not authorized to compare one or more of the selected sessions.</div>}
      {problem && <ErrorState message={problem.message} code={problem.requestId ?? problem.code} onRetry={problem.status && problem.status < 500 && problem.status !== 429 ? undefined : () => setReloadKey((key) => key + 1)} />}
      {loading && <LoadingSkeleton kind="card" count={2} />}

      {comparison && !loading && (
        <>
          {comparison.status === "PARTIAL_EVIDENCE" && <div className="banner info" role="status"><b>Partial evidence.</b> Some metrics have no valid evidence for one or more sessions; those cells state the reason instead of showing a value.</div>}
          {comparison.status === "INSUFFICIENT_EVIDENCE" && <div className="banner warning" role="status"><b>Insufficient evidence.</b> None of the selected sessions has enough valid evidence to compare; nothing was converted to zero.</div>}

          <section className="table-card" aria-labelledby="compat-heading">
            <h2 id="compat-heading">Compatibility</h2>
            <p style={{ margin: "0 0 10px" }}>
              {comparison.compatibility.compatible ? <span className="badge badge-success">Comparable</span> : <span className="badge badge-warning">Compare with caution</span>}{" "}
              <span className="muted">{warningNotices.length} warning{warningNotices.length === 1 ? "" : "s"} · {infoNotices.length} note{infoNotices.length === 1 ? "" : "s"}</span>
            </p>
            {notices.length === 0 && <p className="muted">No compatibility concerns were found for these sessions.</p>}
            <ul className="match-list">
              {warningNotices.map((notice, index) => <li className="banner warning" style={{ margin: 0 }} key={`${notice.code}-${index}`}><AlertTriangle size={16} aria-hidden="true" /><span>{notice.message}</span></li>)}
              {infoNotices.map((notice, index) => <li className="banner info" style={{ margin: 0 }} key={`${notice.code}-${index}`}><Info size={16} aria-hidden="true" /><span>{notice.message}</span></li>)}
            </ul>
          </section>

          <section className="table-card" aria-labelledby="metric-heading">
            <h2 id="metric-heading">Metric</h2>
            <label className="field" style={{ maxWidth: 360 }}><span>Metric to chart</span>
              <select aria-label="Comparison metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
                {METRIC_OPTIONS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            {chartData.every((d) => d.value == null) ? (
              <div className="empty">No selected session has available evidence for {METRIC_LABEL[metric]}.</div>
            ) : (
              <div role="img" aria-label={`Bar chart comparing ${METRIC_LABEL[metric]} across ${sessionRows.length} sessions. Values are also listed in the comparison table below.`}>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={chartData}>
                    <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="name" stroke="var(--text-muted)" />
                    <YAxis domain={METRIC_KIND[metric] === "percent" ? [0, 100] : undefined} stroke="var(--text-muted)" />
                    <Tooltip content={<CustomTooltip kind={METRIC_KIND[metric]} />} />
                    <Legend />
                    <Bar dataKey="value" name={METRIC_LABEL[metric]} fill="var(--chart-2)" isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="table-card" aria-labelledby="overview-heading">
            <h2 id="overview-heading">Indicators at a glance</h2>
            <p className="muted">Percentage-based indicators grouped by session. A missing bar means unavailable evidence, not zero.</p>
            {grouped.every((row) => sessionRows.every((session) => (row as any)[session.name] == null)) ? <div className="empty">No percentage-based indicator has available evidence.</div> : (
              <div role="img" aria-label="Grouped bar chart of percentage-based indicators for each selected session. The comparison table lists every value.">
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={grouped}>
                    <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="metric" stroke="var(--text-muted)" />
                    <YAxis domain={[0, 100]} stroke="var(--text-muted)" />
                    <Tooltip /><Legend />
                    {sessionRows.map((row, index) => <Bar key={row.session_id} dataKey={row.name} fill={SERIES[index % SERIES.length]} isAnimationActive={false} />)}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="table-card" aria-labelledby="evidence-heading">
            <h2 id="evidence-heading">Evidence quality by session</h2>
            <div className="split">
              <div><h3>Coverage (%)</h3>{coverageData.every((d) => d.value == null) ? <div className="empty">Coverage is unavailable.</div> : <SessionBars data={coverageData} name="Coverage (%)" color="var(--chart-1)" domain={[0, 100]} label="Bar chart of evidence coverage per session; values are in the table below." />}</div>
              <div><h3>Confidence (%)</h3>{confidenceData.every((d) => d.value == null) ? <div className="empty">Confidence is unavailable for these sessions.</div> : <SessionBars data={confidenceData} name="Confidence (%)" color="var(--chart-4)" domain={[0, 100]} label="Bar chart of evidence confidence per session; values are in the table below." />}</div>
            </div>
            <h3>Valid observations · {METRIC_LABEL[metric]}</h3>
            {validData.every((d) => d.value == null) ? <div className="empty">No observation counts are available.</div> : <SessionBars data={validData} name="Valid observations" color="var(--chart-3)" label="Bar chart of valid observations per session for the charted metric; values are in the table below." />}
            <div className="table-scroll">
              <table className="data-table">
                <caption>Evidence quality table</caption>
                <thead><tr><th scope="col">Session</th><th scope="col" className="num">Coverage</th><th scope="col" className="num">Confidence</th><th scope="col" className="num">Valid observations</th><th scope="col" className="num">Total observations</th><th scope="col">Status</th></tr></thead>
                <tbody>
                  {sessionRows.map((row) => { const contract = cell(metric, row.session_id); return (
                    <tr key={row.session_id}>
                      <th scope="row" data-th="Session">{row.name}</th>
                      <td className="num" data-th="Coverage">{row.coverage != null ? `${Math.round(row.coverage * 100)}%` : "Unavailable"}</td>
                      <td className="num" data-th="Confidence">{row.confidence != null ? `${Math.round(row.confidence * 100)}%` : "Unavailable"}</td>
                      <td className="num" data-th="Valid observations">{contract?.valid_observations ?? "—"}</td>
                      <td className="num" data-th="Total observations">{contract?.total_observations ?? "—"}</td>
                      <td data-th="Status"><StatusBadge status={row.status} /></td>
                    </tr>); })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="table-card" aria-labelledby="events-heading">
            <h2 id="events-heading">Event frequency</h2>
            <p className="muted">Counts of stored events per type, excluding events a reviewer marked incorrect or excluded. Events are observations, not judgements.</p>
            {eventTypes.length === 0 ? <div className="empty">No stored events for the selected sessions.</div> : (
              <>
                <div role="img" aria-label="Grouped bar chart of stored event counts by event type for each session; the table below lists every count.">
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={eventData}>
                      <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                      <XAxis dataKey="event" stroke="var(--text-muted)" /><YAxis allowDecimals={false} stroke="var(--text-muted)" /><Tooltip /><Legend />
                      {sessionRows.map((row, index) => <Bar key={row.session_id} dataKey={row.name} fill={SERIES[index % SERIES.length]} isAnimationActive={false} />)}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="table-scroll">
                  <table className="data-table">
                    <caption>Event counts by type</caption>
                    <thead><tr><th scope="col">Event type</th>{sessionRows.map((row) => <th scope="col" className="num" key={row.session_id}>{row.name}</th>)}</tr></thead>
                    <tbody>{eventTypes.map((type) => <tr key={type}><th scope="row" data-th="Event type">{type.replace(/_/g, " ")}</th>{sessionRows.map((row) => <td className="num" data-th={row.name} key={row.session_id}>{row.event_counts?.[type] ?? 0}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              </>
            )}
          </section>

          <section className="table-card" aria-labelledby="regions-heading">
            <h2 id="regions-heading">Region comparison</h2>
            {regionEvidence.length === 0 ? <LoadingSkeleton kind="row" count={1} /> : !regionsComparable ? (
              <EmptyState title="Region comparison is not available" description={`Regions are compared only when every selected session used the same calibrated layout; ${regionReason}. No region values were estimated.`} />
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <caption>Anonymous unique tracks per region (layout version {regionEvidence[0].layout_version})</caption>
                  <thead><tr><th scope="col">Region</th>{sessionRows.map((row) => <th scope="col" className="num" key={row.session_id}>{row.name}</th>)}</tr></thead>
                  <tbody>{regionKeys.map((key) => <tr key={key}><th scope="row" data-th="Region">{regionEvidence.flatMap((row) => row.regions ?? []).find((region) => region.region_id === key)?.name ?? key}</th>{regionEvidence.map((row) => { const region = row.regions?.find((entry) => entry.region_id === key); return <td className="num" data-th={sessionRows.find((s) => s.session_id === row.session_id)?.name} key={row.session_id}>{region ? region.estimated_unique_tracks : "—"}</td>; })}</tr>)}</tbody>
                </table>
              </div>
            )}
          </section>

          <section className="table-card" aria-labelledby="table-heading">
            <h2 id="table-heading">Comparison table</h2>
            <div className="table-scroll">
              <table className="data-table">
                <caption className="sr-only">Every compared metric for each selected session, with availability, coverage and confidence</caption>
                <thead>
                  <tr><th scope="col">Metric</th>{sessionRows.map((s) => <th scope="col" key={s.session_id}>{s.name}</th>)}</tr>
                </thead>
                <tbody>
                  {METRIC_OPTIONS.map(([key, label, kind]) => (
                    <tr key={key}>
                      <th scope="row" data-th="Metric">{label}</th>
                      {sessionRows.map((s) => {
                        const contract = cell(key, s.session_id);
                        return (
                          <td key={s.session_id} data-th={s.name} className={contract?.available ? "" : "unavailable"}>
                            <span>{formatMetricAvailability(contract, { kind, noun: METRIC_NOUN[key] })}</span>
                            {contract && contract.total_observations > 0 && <small>{contract.valid_observations} of {contract.total_observations} observations valid</small>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">Each cell states the value with coverage and confidence, or the reason it is unavailable. Unavailable is never shown as zero or blank.</p>
          </section>
        </>
      )}
    </>
  );
}
