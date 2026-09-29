/* eslint-disable react-hooks/set-state-in-effect -- trend loads synchronize remote API state whenever the applied filters change */
import { BarChart3, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { MetricExplainer, PrivacyNotice } from "../components/PrivacyNotice";
import { formatMetricAvailability, readableReason } from "../components/MetricValue";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { ACTIVITY_CONTEXTS, DATA_SOURCES, METRIC_LABELS, TREND_METRICS, apiProblem, contextLabel, isForbidden, type ApiProblem } from "../constants";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api } from "../services/api";
import type { MetricAvailability } from "../types";

const DEFAULTS = { metric: "observable_participation", classroom: "", course: "", activity: "", period: "weekly", source: "REAL", start: "", end: "", min_coverage: "", min_confidence: "" };
type Filters = typeof DEFAULTS;
const COUNT_METRICS = new Set(["occupancy", "peak_occupancy", "unoccupied_capacity"]);
const SERIES_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];
const SERIES_DASH = [undefined, "6 3", "2 3"];

type TrendPoint = { bucket: string; series: string; context: string; methodology_version: string; result?: MetricAvailability; session_count: number; contributing_sessions: number; coverage: number | null; confidence: number | null; reason: string | null };
type TrendResponse = { points: TrendPoint[]; period: string; metric: string; data_source: string; excluded_by_filters?: number; aggregation_rule?: string };

/** Validation of the draft form; every message is tied to a field for aria-describedby. */
export function validateFilters(filters: Filters): Partial<Record<keyof Filters, string>> {
  const errors: Partial<Record<keyof Filters, string>> = {};
  if (filters.start && filters.end && filters.start > filters.end) errors.end = "End date must not be before the start date.";
  for (const key of ["min_coverage", "min_confidence"] as const) {
    if (filters[key] === "") continue;
    const value = Number(filters[key]);
    if (!Number.isFinite(value) || value < 0 || value > 100) errors[key] = "Enter a percentage from 0 to 100.";
  }
  return errors;
}

/**
 * One chart row per period. Only an available canonical result carries a number; anything else is null so the
 * line breaks (connectNulls=false) instead of implying a measured value. A genuine 0 stays 0.
 */
export function buildChartRows(points: TrendPoint[]): Array<Record<string, any>> {
  const rows = new Map<string, Record<string, any>>();
  for (const point of points) {
    const row = rows.get(point.bucket) ?? { bucket: point.bucket };
    row[point.series] = point.result?.available ? point.result.value : null;
    row[`${point.series}__contract`] = point.result;
    rows.set(point.bucket, row);
  }
  return Array.from(rows.values());
}

function TrendTooltip({ active, payload, label, kind }: { active?: boolean; payload?: any[]; label?: string; kind: "percent" | "count" }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="notice" style={{ maxWidth: 300, margin: 0 }}>
      <b>{label}</b>
      {payload.map((entry) => {
        const contract: MetricAvailability | undefined = entry.payload?.[`${entry.dataKey}__contract`];
        return <p key={entry.dataKey} style={{ margin: "4px 0 0" }}><b>{contextLabel(String(entry.dataKey))}:</b> {contract ? formatMetricAvailability(contract, { kind }) : "Unavailable"}</p>;
      })}
    </div>
  );
}

function availabilityLabel(result: MetricAvailability | undefined): string {
  if (!result) return "Unavailable";
  if (result.available) return "Available";
  return result.reason === "insufficient_valid_observations" ? "Insufficient evidence" : "Unavailable";
}

export function AnalyticsWorkspacePage() {
  const { applied, draft, update, apply, reset, activeCount, dirty } = useUrlFilters(DEFAULTS);
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [courses, setCourses] = useState<any[]>([]);
  const [trends, setTrends] = useState<TrendResponse | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "error" | "forbidden" | "invalid">("loading");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const errors = validateFilters(draft);
  const hasErrors = Object.keys(errors).length > 0;
  const kind: "percent" | "count" = COUNT_METRICS.has(applied.metric) ? "count" : "percent";

  useEffect(() => {
    Promise.all([api.get("/v1/classrooms"), api.get("/v1/courses")])
      .then(([rooms, courseList]) => { setClassrooms(Array.isArray(rooms.data) ? rooms.data : []); setCourses(Array.isArray(courseList.data) ? courseList.data : []); })
      .catch(() => { /* filter options are optional; the page still works with "All" */ });
  }, []);

  useEffect(() => {
    let cancelled = false; // a slower, older response must never overwrite a newer one
    setState("loading"); setProblem(null);
    const params = {
      period: applied.period, metric: applied.metric, data_source: applied.source,
      classroom_id: applied.classroom || undefined, course_id: applied.course || undefined, activity_context: applied.activity || undefined,
      start_date: applied.start || undefined, end_date: applied.end ? `${applied.end}T23:59:59` : undefined,
      minimum_coverage: applied.min_coverage !== "" ? Number(applied.min_coverage) / 100 : undefined,
      confidence_min: applied.min_confidence !== "" ? Number(applied.min_confidence) / 100 : undefined,
    };
    api.get("/v1/analytics/trends", { params })
      .then((response) => { if (cancelled) return; setTrends(response.data); setUpdatedAt(new Date()); setState("ok"); })
      .catch((error) => {
        if (cancelled) return;
        const failure = apiProblem(error, "Trend evidence could not be loaded.");
        setProblem(failure);
        setState(isForbidden(failure) ? "forbidden" : failure.status === 400 ? "invalid" : "error");
      });
    return () => { cancelled = true; };
  }, [applied, reloadKey]);

  const points = useMemo(() => trends?.points ?? [], [trends]);
  const series = useMemo(() => Array.from(new Set(points.map((point) => point.series))), [points]);
  const chartData = useMemo(() => buildChartRows(points), [points]);
  const availablePoints = points.filter((point) => point.result?.available);
  const coverages = availablePoints.map((point) => point.coverage).filter((value): value is number => value != null);
  const totals = points.reduce((sum, point) => ({ valid: sum.valid + (point.result?.valid_observations ?? 0), total: sum.total + (point.result?.total_observations ?? 0), sessions: sum.sessions + point.session_count }), { valid: 0, total: 0, sessions: 0 });
  const chips: string[] = [];
  if (applied.classroom) chips.push(`Classroom: ${classrooms.find((room) => String(room.id) === applied.classroom)?.name ?? applied.classroom}`);
  if (applied.course) chips.push(`Course: ${courses.find((course) => String(course.id) === applied.course)?.code ?? applied.course}`);
  if (applied.activity) chips.push(`Activity: ${contextLabel(applied.activity)}`);
  if (applied.start) chips.push(`From ${applied.start}`);
  if (applied.end) chips.push(`To ${applied.end}`);
  if (applied.min_coverage) chips.push(`Coverage ≥ ${applied.min_coverage}%`);
  if (applied.min_confidence) chips.push(`Confidence ≥ ${applied.min_confidence}%`);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Trends</h1>
          <p>Filtered, anonymous evidence over time. Real sessions are selected by default. See <Link to="/compare">Compare sessions</Link> for a side-by-side view.</p>
        </div>
        <div className="page-status" aria-live="polite">
          {updatedAt && <span>Last updated {updatedAt.toLocaleTimeString()}</span>}
        </div>
      </div>
      <PrivacyNotice variant="compact" showValidation />

      <form className="filter-panel" aria-label="Trend filters" onSubmit={(event) => { event.preventDefault(); if (!hasErrors) apply(); }}>
        <h2>Trend filters {activeCount > 0 && <span className="count-pill" aria-label={`${activeCount} active filters`}>{activeCount} active</span>}</h2>
        <div className="filter-grid">
          <label className="field"><span>Metric</span>
            <select value={draft.metric} onChange={(event) => update("metric", event.target.value)}>
              {TREND_METRICS.map((key) => <option key={key} value={key}>{METRIC_LABELS[key]}</option>)}
            </select>
          </label>
          <label className="field"><span>Classroom</span>
            <select value={draft.classroom} onChange={(event) => update("classroom", event.target.value)}>
              <option value="">All classrooms</option>
              {classrooms.map((room) => <option key={room.id} value={room.id}>{room.name}</option>)}
            </select>
          </label>
          <label className="field"><span>Course</span>
            <select value={draft.course} onChange={(event) => update("course", event.target.value)}>
              <option value="">All courses</option>
              {courses.map((course) => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}
            </select>
          </label>
          <label className="field"><span>Activity context</span>
            <select value={draft.activity} onChange={(event) => update("activity", event.target.value)}>
              <option value="">All activities</option>
              {ACTIVITY_CONTEXTS.map((value) => <option key={value} value={value}>{contextLabel(value)}</option>)}
            </select>
          </label>
          <label className="field"><span>Period</span>
            <select value={draft.period} onChange={(event) => update("period", event.target.value)}>
              <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option>
            </select>
          </label>
          <label className="field"><span>Data source</span>
            <select value={draft.source} onChange={(event) => update("source", event.target.value)}>
              {DATA_SOURCES.map((source) => <option key={source.value} value={source.value}>{source.label}</option>)}
            </select>
          </label>
          <label className="field"><span>Start date</span>
            <input type="date" value={draft.start} onChange={(event) => update("start", event.target.value)} />
          </label>
          <div className="field"><label htmlFor="f-end">End date</label>
            <input id="f-end" type="date" value={draft.end} aria-invalid={Boolean(errors.end)} aria-describedby={errors.end ? "end-error" : undefined} onChange={(event) => update("end", event.target.value)} />
            {errors.end && <p className="field-error" id="end-error" role="alert">{errors.end}</p>}
          </div>
          <div className="field"><label htmlFor="f-coverage">Minimum coverage (%)</label>
            <input id="f-coverage" type="number" inputMode="decimal" min={0} max={100} step="any" placeholder="Any" value={draft.min_coverage} aria-invalid={Boolean(errors.min_coverage)} aria-describedby={errors.min_coverage ? "coverage-error" : "coverage-hint"} onChange={(event) => update("min_coverage", event.target.value)} />
            {errors.min_coverage ? <p className="field-error" id="coverage-error" role="alert">{errors.min_coverage}</p> : <p className="field-hint" id="coverage-hint">Hide periods backed by less evidence.</p>}
          </div>
          <div className="field"><label htmlFor="f-confidence">Minimum confidence (%)</label>
            <input id="f-confidence" type="number" inputMode="decimal" min={0} max={100} step="any" placeholder="Any" value={draft.min_confidence} aria-invalid={Boolean(errors.min_confidence)} aria-describedby={errors.min_confidence ? "confidence-error" : undefined} onChange={(event) => update("min_confidence", event.target.value)} />
            {errors.min_confidence && <p className="field-error" id="confidence-error" role="alert">{errors.min_confidence}</p>}
          </div>
        </div>
        <div className="filter-actions">
          <button type="submit" className="button" disabled={hasErrors || !dirty}>Apply filters</button>
          <button type="button" className="button secondary" onClick={() => reset()} disabled={activeCount === 0 && !dirty}><RotateCcw size={14} /> Reset</button>
          {dirty && !hasErrors && <span className="muted">Changes are not applied yet.</span>}
        </div>
        {chips.length > 0 && <ul className="chip-list" style={{ marginTop: 12 }} aria-label="Applied filters">{chips.map((chip) => <li className="chip" key={chip}>{chip}</li>)}</ul>}
      </form>

      <MetricExplainer metric={applied.metric} />

      {state === "loading" && <LoadingSkeleton kind="card" count={2} />}
      {state === "forbidden" && <EmptyState title="You are not authorized to view this analytics scope" description="Ask an administrator for access to the selected classroom or course, or clear those filters." />}
      {state === "invalid" && <ErrorState title="These filters are not valid" message={problem?.message ?? "The server rejected the filters."} code={problem?.code} />}
      {state === "error" && <ErrorState message={problem?.message ?? "Trend evidence could not be loaded."} code={problem?.requestId} onRetry={() => setReloadKey((key) => key + 1)} />}

      {state === "ok" && points.length === 0 && (
        <EmptyState title="No sessions match these filters" description={trends?.excluded_by_filters ? `${trends.excluded_by_filters} period(s) were hidden by the minimum coverage or confidence filter.` : "Try a wider date range, another data source, or reset the filters."} action={activeCount > 0 ? <button className="button secondary" onClick={() => reset()}>Reset filters</button> : undefined} />
      )}

      {state === "ok" && points.length > 0 && (
        <>
          <div className="summary-grid" aria-label="Trend summary">
            <article><small>Periods shown</small><b>{new Set(points.map((point) => point.bucket)).size}</b></article>
            <article><small>Sessions included</small><b>{totals.sessions}</b></article>
            <article><small>Periods with evidence</small><b>{availablePoints.length} of {points.length}</b></article>
            <article><small>Average coverage</small><b>{coverages.length ? `${Math.round((coverages.reduce((a, b) => a + b, 0) / coverages.length) * 100)}%` : "Unavailable"}</b></article>
            <article><small>Valid / total observations</small><b>{totals.valid} / {totals.total}</b></article>
          </div>
          {(trends?.excluded_by_filters ?? 0) > 0 && <div className="banner info" role="status">{trends?.excluded_by_filters} period(s) were hidden by the minimum coverage or confidence filter.</div>}
          {availablePoints.length === 0 && <div className="banner warning" role="status"><b>Insufficient evidence.</b> No period has valid evidence for {METRIC_LABELS[applied.metric]?.toLowerCase()}; every period below is shown as unavailable (a gap), never as zero.</div>}
          {availablePoints.length > 0 && availablePoints.length < points.length && <div className="banner info" role="status"><b>Partial evidence.</b> {availablePoints.length} of {points.length} periods have available evidence; the rest appear as gaps in the chart.</div>}

          <section className="chart-card" aria-labelledby="trend-chart-title">
            <h2 id="trend-chart-title"><BarChart3 size={16} style={{ verticalAlign: "-2px" }} aria-hidden="true" /> {METRIC_LABELS[applied.metric] ?? applied.metric}</h2>
            <p>Each line is one activity context. Gaps mean unavailable evidence. The full data is in the table below.</p>
            <div role="img" aria-label={`Line chart of ${METRIC_LABELS[applied.metric] ?? applied.metric} by ${applied.period} period. ${availablePoints.length} of ${points.length} periods have available evidence. A table with every value follows.`}>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={chartData}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="bucket" stroke="var(--text-muted)" />
                  <YAxis domain={kind === "percent" ? [0, 100] : undefined} stroke="var(--text-muted)" />
                  <Tooltip content={<TrendTooltip kind={kind} />} />
                  <Legend formatter={(value) => contextLabel(String(value))} />
                  {series.map((name, index) => (
                    <Line key={name} type="monotone" connectNulls={false} dataKey={name} stroke={SERIES_COLORS[index % SERIES_COLORS.length]} strokeDasharray={SERIES_DASH[Math.floor(index / SERIES_COLORS.length) % SERIES_DASH.length]} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="table-card table-scroll" aria-labelledby="trend-table-title">
            <table className="data-table">
              <caption id="trend-table-title">Trend evidence by period and series ({points.length} rows, chronological)</caption>
              <thead>
                <tr>
                  <th scope="col">Period</th><th scope="col">Series</th><th scope="col" className="num">Value</th><th scope="col">Availability</th><th scope="col">Reason</th>
                  <th scope="col" className="num">Coverage</th><th scope="col" className="num">Confidence</th><th scope="col" className="num">Valid observations</th><th scope="col" className="num">Total observations</th><th scope="col" className="num">Session count</th>
                </tr>
              </thead>
              <tbody>
                {points.map((point) => {
                  const result = point.result;
                  const available = Boolean(result?.available);
                  return (
                    <tr key={`${point.bucket}-${point.series}-${point.methodology_version}`}>
                      <th scope="row" data-th="Period">{point.bucket}</th>
                      <td data-th="Series">{contextLabel(point.series)}</td>
                      <td className={`num ${available ? "" : "unavailable"}`} data-th="Value">{available && result?.value != null ? `${result.value}${kind === "percent" ? "%" : ""}` : "—"}</td>
                      <td data-th="Availability">{availabilityLabel(result)}</td>
                      <td data-th="Reason">{available ? "—" : readableReason(result?.reason ?? point.reason)}</td>
                      <td className="num" data-th="Coverage">{result?.coverage != null ? `${Math.round(result.coverage * 100)}%` : "—"}</td>
                      <td className="num" data-th="Confidence">{result?.confidence != null ? `${Math.round(result.confidence * 100)}%` : "—"}</td>
                      <td className="num" data-th="Valid observations">{result?.valid_observations ?? 0}</td>
                      <td className="num" data-th="Total observations">{result?.total_observations ?? 0}</td>
                      <td className="num" data-th="Session count">{point.session_count}{point.contributing_sessions !== point.session_count ? ` (${point.contributing_sessions} contributing)` : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {trends?.aggregation_rule && <p className="muted">{trends.aggregation_rule}</p>}
          </section>
        </>
      )}
    </>
  );
}
