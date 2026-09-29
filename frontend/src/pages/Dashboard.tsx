import {
  Camera, CheckCircle2, Clock, FileText, Gauge, GitCompare, Loader2, PlayCircle, RefreshCw,
  School, Upload as UploadIcon, Users, XCircle,
} from "lucide-react";
/* eslint-disable react-hooks/set-state-in-effect -- dashboard overview/trends synchronize remote API state as filters change */
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { PageHeader, StatCard } from "../components/Card";
import { QualityBadge, StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { api } from "../services/api";

// The charting library is code-split: the Dashboard paints its cards first and the chart streams in.
const DashboardTrendChart = lazy(() => import("../components/DashboardTrendChart"));

type Overview = {
  session_counts: Record<string, number>;
  reports_available: number;
  classrooms_configured: number;
  average_valid_observation_coverage: number | null;
  data_quality: { tiers: Record<string, number>; thresholds: { high_min_coverage: number; moderate_min_coverage: number; definition: string } };
  recent_sessions: Array<{ id: number; name: string; classroom_id: number | null; activity_context: string; source_type: string; status: string; created_at: string; duration: number; coverage: number | null }>;
  recent_reports: Array<{ session_id: number; session_name: string; format: string; created_at: string }>;
  recent_events: Array<{ session_id: number; timestamp: number; event_type: string; severity: string; review_state: string }>;
};

const TREND_METRICS = [
  ["observable_participation", "Observable participation"],
  ["visual_orientation", "Visual orientation"],
  ["possible_fatigue", "Possible fatigue"],
  ["occupancy", "Occupancy"],
] as const;

export function Dashboard() {
  const { can } = useAuth();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [classroom, setClassroom] = useState("");
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [dataSource, setDataSource] = useState("REAL");
  const [trendMetric, setTrendMetric] = useState<string>("observable_participation");
  const [trends, setTrends] = useState<any>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      api.get("/v1/dashboard/overview", { params: { classroom_id: classroom || undefined, data_source: dataSource } }),
      api.get("/v1/analytics/trends", { params: { period: "daily", metric: trendMetric, data_source: dataSource, classroom_id: classroom || undefined } }),
    ])
      .then(([a, b]) => {
        if (cancelled) return;
        setOverview(a.data);
        setTrends(b.data);
        setLastUpdated(new Date());
      })
      .catch((e: any) => {
        if (cancelled) return;
        setError(e.response?.data?.detail?.error?.message || e.response?.data?.detail || "The dashboard could not be loaded.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [classroom, dataSource, trendMetric]);
  useEffect(() => load(), [load]);
  useEffect(() => { api.get("/v1/classrooms").then((r) => setClassrooms(Array.isArray(r.data) ? r.data : [])).catch(() => {}); }, []);

  const chartData = useMemo(() => {
    if (!trends?.points) return [];
    return trends.points.map((p: any) => ({ bucket: p.bucket, value: p.result?.available ? p.result.value : null, __contract: p.result }));
  }, [trends]);

  const counts = overview?.session_counts;
  const processingCount = (counts?.processing || 0) + (counts?.initializing || 0) + (counts?.decoding || 0) + (counts?.aggregating || 0) + (counts?.generating_report || 0);

  return (
    <>
      <PageHeader
        title="Overview"
        description="Anonymous, observational classroom signals. Not attendance, performance, or a medical/psychological assessment."
        actions={
          <>
            <select aria-label="Classroom filter" value={classroom} onChange={(e) => setClassroom(e.target.value)}>
              <option value="">All classrooms</option>
              {classrooms.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <select aria-label="Data source" value={dataSource} onChange={(e) => setDataSource(e.target.value)}>
              <option value="REAL">Real only</option>
              <option value="DEMO">Demo only</option>
              <option value="ALL">All data</option>
            </select>
            <button className="button secondary" onClick={load} disabled={loading}>
              <RefreshCw size={15} className={loading ? "spin" : undefined} /> Refresh
            </button>
          </>
        }
      />
      <div className="notice">AmbiSense estimates observable classroom signals. It does not make medical, psychological, or pedagogical diagnoses. Results must not be the sole basis for grading, discipline, or attendance decisions.</div>
      {lastUpdated && !error && <p className="muted" style={{ marginTop: 4 }}>Last updated {lastUpdated.toLocaleTimeString()}</p>}

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading && !overview ? (
        <div className="metrics"><LoadingSkeleton kind="card" count={6} /></div>
      ) : overview ? (
        <>
          <div className="metrics">
            <StatCard label="Active sessions" value={processingCount} icon={Loader2} tone="info" tooltip="Sessions currently initializing, decoding, processing, aggregating, or generating a report." />
            <StatCard label="Completed sessions" value={counts?.completed ?? 0} icon={CheckCircle2} tone="success" tooltip="Sessions that finished processing successfully." />
            <StatCard label="Failed sessions" value={counts?.failed ?? 0} icon={XCircle} tone="danger" tooltip="Sessions where processing failed." />
            <StatCard label="Available reports" value={overview.reports_available} icon={FileText} tooltip="Sessions with at least one generated report (CSV, PDF, or metrics)." />
            <StatCard label="Configured classrooms" value={overview.classrooms_configured} icon={School} tooltip="Active classrooms you can access." />
            <StatCard
              label="Average valid-observation coverage"
              value={overview.average_valid_observation_coverage == null ? null : Math.round(overview.average_valid_observation_coverage * 100)}
              unit={overview.average_valid_observation_coverage == null ? undefined : "%"}
              icon={Gauge}
              tone="violet"
              tooltip="Average fraction of processed frames with at least one detected person, across sessions matching the current filters."
            />
          </div>

          <section className="table-card">
            <h2>Processing overview</h2>
            <div className="summary-grid">
              {["queued", "initializing", "processing", "aggregating", "generating_report", "completed", "failed"].map((key) => (
                <article key={key}>
                  <small>{key.replace(/_/g, " ")}</small>
                  <b>{counts?.[key] ?? 0}</b>
                </article>
              ))}
            </div>
            <Link to="/sessions">View all sessions →</Link>
          </section>

          <div className="live-layout dash-split">
            <section className="chart-card">
              <h2>Trend preview</h2>
              <select aria-label="Trend metric" value={trendMetric} onChange={(e) => setTrendMetric(e.target.value)} style={{ marginBottom: 12 }}>
                {TREND_METRICS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
              {chartData.length === 0 ? (
                <EmptyState title="No trend evidence" description="No sessions with available evidence match the current filters yet." />
              ) : chartData.every((d: any) => d.value == null) ? (
                <EmptyState title="Insufficient evidence" description={`No valid evidence exists yet for ${trendMetric.replace(/_/g, " ")} in this range.`} />
              ) : (
                <Suspense fallback={<LoadingSkeleton kind="card" />}>
                  <DashboardTrendChart data={chartData} name={TREND_METRICS.find((m) => m[0] === trendMetric)?.[1]} />
                </Suspense>
              )}
              <Link to="/analytics-workspace">Open full Analytics →</Link>
            </section>

            <section className="table-card">
              <h2>Data quality summary</h2>
              <p className="muted">Coverage tiers: HIGH ≥{Math.round(overview.data_quality.thresholds.high_min_coverage * 100)}%, MODERATE ≥{Math.round(overview.data_quality.thresholds.moderate_min_coverage * 100)}%, LOW below that, INSUFFICIENT EVIDENCE when no frames were processed.</p>
              {Object.entries(overview.data_quality.tiers).map(([tier, count]) => (
                <p key={tier}><QualityBadge tier={tier} /> <b style={{ marginLeft: 8 }}>{count}</b> session{count === 1 ? "" : "s"}</p>
              ))}
            </section>
          </div>

          <section className="table-card">
            <h2>Recent sessions</h2>
            {overview.recent_sessions.length === 0 ? (
              <EmptyState title="No sessions found" description={can("ADMINISTRATOR", "INSTRUCTOR") ? "Upload a video or start a live session to begin." : "No sessions are available to you yet."} action={can("ADMINISTRATOR", "INSTRUCTOR") && <Link className="button" to="/upload">Upload video</Link>} />
            ) : (
              <table>
                <thead><tr><th>Session</th><th>Activity</th><th>Source</th><th>Status</th><th>Date</th><th>Coverage</th><th>Action</th></tr></thead>
                <tbody>
                  {overview.recent_sessions.map((s) => (
                    <tr key={s.id}>
                      <td>{s.name}</td>
                      <td>{s.activity_context.replace(/_/g, " ")}</td>
                      <td>{s.source_type}</td>
                      <td><StatusBadge status={s.status} /></td>
                      <td>{new Date(s.created_at).toLocaleDateString()}</td>
                      <td>{s.coverage == null ? "Unavailable" : `${Math.round(s.coverage * 100)}%`}</td>
                      <td><Link to={`/sessions/${s.id}`}>Open</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <div className="detail-layout">
            <section className="table-card">
              <h2>Recent reports</h2>
              {overview.recent_reports.length === 0 ? (
                <EmptyState title="No completed reports" description="Reports appear here once a session finishes processing." />
              ) : (
                overview.recent_reports.map((r, i) => (
                  <p key={i}>
                    <b>{r.session_name}</b> · {r.format.toUpperCase()} · {new Date(r.created_at).toLocaleString()}
                    {" · "}
                    <a href={`/api/sessions/${r.session_id}/report?format=${r.format}`}>Download</a>
                  </p>
                ))
              )}
            </section>
            <section className="table-card">
              <h2>Recent events</h2>
              {overview.recent_events.length === 0 ? (
                <EmptyState title="No recent events" />
              ) : (
                overview.recent_events.slice(0, 8).map((e, i) => (
                  <p key={i}><StatusBadge status={e.severity} label={e.severity} /> {e.event_type.replace(/_/g, " ")} · session <Link to={`/sessions/${e.session_id}`}>#{e.session_id}</Link></p>
                ))
              )}
            </section>
          </div>

          <section className="table-card">
            <h2>Quick actions</h2>
            <div className="actions">
              {can("ADMINISTRATOR", "INSTRUCTOR") && <Link className="button" to="/live"><PlayCircle size={15} /> Start live session</Link>}
              {can("ADMINISTRATOR", "INSTRUCTOR") && <Link className="button secondary" to="/upload"><UploadIcon size={15} /> Upload video</Link>}
              <Link className="button secondary" to="/sessions"><Users size={15} /> View sessions</Link>
              <Link className="button secondary" to="/compare"><GitCompare size={15} /> Compare sessions</Link>
              {can("ADMINISTRATOR", "INSTRUCTOR") && <Link className="button secondary" to="/classroom-setup"><Camera size={15} /> Configure classroom</Link>}
              <Link className="button secondary" to="/reports"><Clock size={15} /> Open reports</Link>
            </div>
          </section>
        </>
      ) : (
        <EmptyState title="No data available" />
      )}
    </>
  );
}
