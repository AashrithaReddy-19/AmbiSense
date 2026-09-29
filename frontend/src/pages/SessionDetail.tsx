/* eslint-disable react-hooks/set-state-in-effect -- session detail synchronizes remote API state whenever the route id changes */
import { CheckCircle2, Download, GitCompare, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../auth/AuthContext";
import { ArtifactList, type Artifact } from "../components/ArtifactList";
import { AudioStatus } from "../components/AudioStatus";
import { useBreadcrumbLabel } from "../components/Breadcrumbs";
import { ConfirmDialog } from "../components/Dialog";
import { EventReviewRow } from "../components/EventReviewRow";
import { formatMetricAvailability, MetricValue, readableReason } from "../components/MetricValue";
import { MetricExplainer, PrivacyNotice } from "../components/PrivacyNotice";
import { SessionIntelligence } from "../components/SessionIntelligence";
import { SessionNotes } from "../components/SessionNotes";
import { EmptyState, ErrorState } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { TabPanel, Tabs, type TabDefinition } from "../components/Tabs";
import { useToast } from "../components/Toast";
import { ACTIVITY_CONTEXTS, METRIC_LABELS, apiProblem, formatDateTime, formatDuration } from "../constants";
import { api } from "../services/api";
import { downloadFile, useInFlight } from "../services/download";
import type { Session } from "../types";

const CANONICAL_METRICS: Array<[string, "percent" | "count", string | undefined]> = [
  ["occupancy", "count", "people"], ["peak_occupancy", "count", "people"], ["unoccupied_capacity", "count", "seats"],
  ["visual_orientation", "percent", undefined], ["observable_participation", "percent", undefined], ["prolonged_eye_closure", "count", "events"],
  ["possible_fatigue", "percent", undefined], ["yawning", "count", "events"], ["raised_hands", "count", "events"], ["frame_quality", "percent", undefined],
];
const STATUS_STEPS = ["CREATED", "QUEUED", "INITIALIZING", "DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT", "COMPLETED"];
const DELETABLE_KINDS: Array<[string, string]> = [["source_video", "Original video"], ["annotated_video", "Annotated video"], ["reports", "Generated reports"], ["audio", "Extracted audio"], ["transcript_exports", "Transcript exports"]];
const ACTIVE = new Set(["QUEUED", "DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT", "INITIALIZING", "FINALIZING"]);
const SEVERITY_TONE: Record<string, string> = { CRITICAL: "FAILED", HIGH: "FAILED", WARNING: "INSUFFICIENT_EVIDENCE", MEDIUM: "INSUFFICIENT_EVIDENCE", INFO: "PROCESSING", LOW: "PROCESSING" };

function availabilityText(metric: any): string {
  if (!metric) return "Unavailable";
  if (metric.available) return "Available";
  return metric.reason === "insufficient_valid_observations" ? "Insufficient evidence" : "Unavailable";
}

function ReadOnlyEvent({ event }: { event: any }) {
  return (
    <article className={`note-item severity-${String(event.severity ?? "info").toLowerCase() === "critical" ? "critical" : String(event.severity ?? "").toLowerCase() === "warning" ? "warning" : "info"}`}>
      <header><span><time>{Number(event.timestamp).toFixed(1)}s</time> · <b>{String(event.type).replace(/_/g, " ")}</b></span><span><StatusBadge status={SEVERITY_TONE[String(event.severity).toUpperCase()] ?? "PROCESSING"} label={String(event.severity)} /> <span className="badge badge-neutral">{String(event.review_state ?? "UNREVIEWED").toLowerCase()}</span></span></header>
      <p>{event.message}</p>
      {event.reviewer_note && <small>Reviewer note: {event.reviewer_note}</small>}
    </article>
  );
}

export function SessionDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const { show } = useToast();
  const { run, busy } = useInFlight();
  const [session, setSession] = useState<Session | null>(null);
  const [summary, setSummary] = useState<any>(null);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [quality, setQuality] = useState<any>(null);
  const [regions, setRegions] = useState<any>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [videoUnplayable, setVideoUnplayable] = useState(false);
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [courses, setCourses] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [activity, setActivity] = useState("LECTURE");
  const [visited, setVisited] = useState<Set<string>>(() => new Set(["overview"]));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmArtifacts, setConfirmArtifacts] = useState(false);
  const [kinds, setKinds] = useState<string[]>([]);
  const [audio, setAudio] = useState<any>(null);
  const [capabilities, setCapabilities] = useState<any>(null);
  const canManage = can("ADMINISTRATOR", "INSTRUCTOR");
  const canReview = can("ADMINISTRATOR", "INSTRUCTOR", "REVIEWER");
  useBreadcrumbLabel(session?.name);

  const load = useCallback(() => {
    let cancelled = false;
    setError("");
    Promise.all([
      api.get(`/sessions/${id}`), api.get(`/sessions/${id}/analytics`), api.get(`/sessions/${id}/timeline`), api.get(`/sessions/${id}/events`),
      api.get(`/v1/sessions/${id}/quality`), api.get(`/v1/sessions/${id}/regions`),
      api.get(`/v1/sessions/${id}/artifacts`).catch(() => ({ data: { artifacts: [] } })), // artifacts must never block the page
    ]).then(([a, b, c, d, e, f, g]) => {
      if (cancelled) return;
      setSession(a.data); setSummary(b.data); setTimeline(c.data); setEvents(d.data); setQuality(e.data); setRegions(f.data);
      setArtifacts(Array.isArray(g.data?.artifacts) ? g.data.artifacts : []); setActivity(a.data.activity_context);
    }).catch((err: any) => {
      if (cancelled) return;
      const failure = apiProblem(err, "This session could not be loaded.");
      setError(failure.status === 404 ? "This session was not found." : failure.status === 403 ? "You are not authorized to view this session." : failure.message);
    });
    return () => { cancelled = true; };
  }, [id]);
  useEffect(() => load(), [load]);
  useEffect(() => {
    api.get("/v1/classrooms").then((r) => setClassrooms(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    api.get("/v1/courses").then((r) => setCourses(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  }, []);

  const tabs = useMemo<TabDefinition[]>(() => {
    if (!session) return [];
    const list: TabDefinition[] = [{ id: "overview", label: "Overview" }];
    if (timeline.length > 0 || events.length > 0) list.push({ id: "timeline", label: "Timeline", badge: events.length || null });
    if ((summary?.snapshots ?? 0) > 0 || (quality?.timeline?.length ?? 0) > 0 || (quality?.status && quality.status !== "UNAVAILABLE")) list.push({ id: "evidence", label: "Quality & Evidence" });
    if (session.classroom_id || regions?.status === "CALIBRATED") list.push({ id: "regions", label: "Regions" });
    if (artifacts.length > 0 || session.status === "COMPLETED" || session.annotated_video_path) list.push({ id: "artifacts", label: "Artifacts", badge: artifacts.length || null });
    list.push({ id: "notes", label: "Notes" });
    return list;
  }, [session, timeline, events, summary, quality, regions, artifacts]);
  const requested = params.get("tab");
  const active = tabs.some((tab) => tab.id === requested) ? (requested as string) : "overview";
  const selectTab = useCallback((tab: string) => {
    setVisited((old) => (old.has(tab) ? old : new Set(old).add(tab)));
    setParams((previous) => { const next = new URLSearchParams(previous); if (tab === "overview") next.delete("tab"); else next.set("tab", tab); return next; }, { replace: true });
  }, [setParams]);
  // A deep link such as ?tab=notes counts as a visit so that panel mounts on first render.
  const mounted = useMemo(() => new Set([...visited, active]), [visited, active]);

  // Requested at most once per page view, even if the user leaves and re-enters the tab before the reply arrives.
  const capabilitiesRequested = useRef(false);
  useEffect(() => {
    if (active !== "evidence" || capabilitiesRequested.current) return;
    capabilitiesRequested.current = true;
    api.get("/v1/audio/capabilities").then((r) => setCapabilities(r.data)).catch(() => setCapabilities({ status: "NOT_CONFIGURED", reason: "Audio capability could not be determined." }));
  }, [active]);

  async function download(format: "pdf" | "csv" | "metrics", label: string) {
    show(`${label} download started.`, "info");
    await run(`report:${format}`, async () => {
      try { await downloadFile(`/sessions/${id}/report?format=${format}`, `session_${id}.${format === "pdf" ? "pdf" : "csv"}`); }
      catch (e) { show(apiProblem(e, `${label} could not be downloaded.`).message, "error"); }
    });
  }
  async function remove() {
    setConfirmDelete(false);
    try { await api.delete(`/sessions/${id}`, { params: { confirm: true } }); show("Session deleted.", "success"); navigate("/sessions"); }
    catch (e) { show(apiProblem(e, "This session could not be deleted.").message, "error"); }
  }
  async function removeArtifacts() {
    setConfirmArtifacts(false);
    try { await api.delete(`/v1/sessions/${id}/artifacts`, { params: { kinds: kinds.join(","), confirm: true } }); show("Selected artifacts were deleted; analytics evidence was kept.", "success"); setKinds([]); load(); }
    catch (e) { show(apiProblem(e, "Artifacts could not be deleted.").message, "error"); }
  }
  async function changeActivity(value: string) {
    setActivity(value);
    try {
      await api.post(`/v1/sessions/${id}/activities`, { activity_type: value, start_seconds: timeline.at(-1)?.timestamp || 0, confirmed: true });
      show("Activity context updated.", "success"); load();
    } catch (e) { show(apiProblem(e, "The activity context could not be updated.").message, "error"); }
  }

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!session || !summary) return <div className="state">Loading session evidence…</div>;
  const classroomName = classrooms.find((c) => c.id === session.classroom_id)?.name;
  const courseName = courses.find((c) => c.id === session.course_id)?.code;
  const stepIndex = STATUS_STEPS.indexOf(session.status);
  const isFailed = session.status === "FAILED";
  const reportFormats = new Set(artifacts.filter((a) => a.kind.startsWith("report_")).map((a) => a.kind.replace("report_", "")));
  const reportReady = session.status === "COMPLETED" && reportFormats.has("pdf") && reportFormats.has("csv");
  const qualityRows: any[] = quality?.timeline ?? [];
  const mean = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);
  const brightness = mean(qualityRows.map((row) => row.brightness).filter((v: unknown): v is number => typeof v === "number"));
  const blur = mean(qualityRows.map((row) => row.blur).filter((v: unknown): v is number => typeof v === "number"));
  const lighting = brightness == null ? "Unavailable" : brightness < 45 ? "Underexposed" : brightness > 220 ? "Overexposed" : "Adequate";
  const sharpness = blur == null ? "Unavailable" : blur < 45 ? "Blurred" : "Adequate";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{session.name}</h1>
          <p>Session #{id} · {session.analytics_mode} · <StatusBadge status={session.status} /> · {session.source_type} · {classroomName || "Unassigned classroom"} · {courseName || "No course"}</p>
        </div>
        <div className="actions">
          <Link className="button secondary" to={`/compare?session_ids=${id}`}><GitCompare size={16} />Compare this session</Link>
          {session.status === "COMPLETED" && (
            <>
              <button className="button" disabled={busy("report:pdf")} onClick={() => void download("pdf", "PDF")}><Download size={16} />PDF</button>
              <button className="button secondary" disabled={busy("report:csv")} onClick={() => void download("csv", "CSV")}><Download size={16} />CSV</button>
              <button className="button secondary" disabled={busy("report:metrics")} title="Per-metric value/available/reason/coverage/confidence contract" onClick={() => void download("metrics", "Metrics CSV")}><Download size={16} />Metrics CSV</button>
            </>
          )}
          {canManage && <button className="button danger" onClick={() => setConfirmDelete(true)} disabled={ACTIVE.has(session.status)} title={ACTIVE.has(session.status) ? "Stop processing before deleting" : undefined}><Trash2 size={16} />Delete</button>}
        </div>
      </div>
      {session.stale && <div className="banner warning" role="status"><div><b>This session looks stale.</b> {session.stale_reason} Work that runs inside the API process cannot survive a server restart.{can("ADMINISTRATOR") && <> <Link to="/settings">Review stale sessions in Settings › System.</Link></>}</div></div>}
      {isFailed && <div className="notice error" role="alert">Processing failed: {session.error || "See job details for a safe error reference."}</div>}

      <Tabs tabs={tabs} active={active} onChange={selectTab} label="Session sections" idPrefix="session-tab" />

      <TabPanel id="overview" active={active} idPrefix="session-tab" keepMounted>
        <div className="stack">
          <PrivacyNotice showValidation />
          {!isFailed && session.status !== "COMPLETED" && (
            <section className="table-card">
              <h2>Status</h2>
              <ol style={{ display: "flex", gap: 8, flexWrap: "wrap", listStyle: "none", padding: 0 }} aria-label="Processing status">
                {STATUS_STEPS.map((step, index) => (
                  <li key={step} style={{ opacity: index <= stepIndex ? 1 : 0.4 }}>{index < stepIndex ? <CheckCircle2 size={13} style={{ verticalAlign: "-2px" }} aria-hidden="true" /> : null} {step.replace(/_/g, " ")}</li>
                ))}
              </ol>
              <p className="muted">Started {session.started_at ? formatDateTime(session.started_at) : "not yet"}.</p>
            </section>
          )}
          <section className="table-card" aria-labelledby="meta-heading">
            <h2 id="meta-heading">Session details</h2>
            <div className="session-meta" style={{ margin: 0 }}>
              <span>Source<b>{session.source_type === "LIVE" ? "Live camera" : session.source_filename || "Uploaded video"}</b></span>
              <span>Created<b>{formatDateTime(session.created_at)}</b></span>
              <span>Duration<b>{formatDuration(session.duration)}</b></span>
              <span>Frames<b>{session.processed_frames}/{session.total_frames || "—"}</b></span>
              <span>Quality<b>{quality?.status || "UNAVAILABLE"}</b></span>
              <span>Report<b>{reportReady ? "Ready" : session.status === "COMPLETED" ? "Not generated" : "Pending"}</b></span>
            </div>
            <label className="field" style={{ maxWidth: 320, marginTop: 12 }}>
              <span>Activity context</span>
              <select value={activity} disabled={!canManage} onChange={(e) => void changeActivity(e.target.value)}>
                {ACTIVITY_CONTEXTS.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
          </section>
          {quality?.warnings?.map((w: string) => <div className="notice" key={w}>{w}</div>)}
          <section className="table-card">
            <h2>Summary metrics</h2>
            <div className="live-metrics">
              {CANONICAL_METRICS.map(([key, kind, noun]) => <MetricValue key={key} metric={summary.metric_results?.[key]} kind={kind} noun={noun} label={METRIC_LABELS[key] ?? key} />)}
            </div>
            <details className="metric-explainer"><summary>Metric definitions and limitations</summary>{CANONICAL_METRICS.map(([key]) => <MetricExplainer key={key} metric={key} />)}</details>
          </section>
          <div className="detail-layout">
            <section className="video-panel">
              {session.annotated_video_path
                ? <video controls src={`/api/sessions/${id}/video?annotated=true`} onError={() => setVideoUnplayable(true)} />
                : <div className="video-empty">Annotated video becomes available after real processing completes.</div>}
              {session.annotated_video_path && videoUnplayable && (
                <div className="video-empty" role="status">
                  <b>This browser cannot play the annotated video.</b>
                  <span>The file exists, but its video codec is not supported for in-page playback. Download it to watch it in a desktop video player.</span>
                  <a className="button" href={`/api/sessions/${id}/video?annotated=true`} download>Download annotated video</a>
                </div>
              )}
            </section>
            <div className="summary-grid">
              {[["Peak observable participation", summary.peak_engagement], ["Lowest observable participation", summary.lowest_engagement], ["Average anonymous occupancy", summary.average_students], ["Minimum anonymous occupancy", summary.minimum_students], ["Peak raised hands", summary.peak_raised_hands], ["Total yawns", summary.total_yawns]].map(([key, value]) => (
                <article key={String(key)}><small>{key}</small><b>{value == null ? "Unavailable" : String(value)}</b></article>
              ))}
            </div>
          </div>
        </div>
      </TabPanel>

      {mounted.has("timeline") && tabs.some((t) => t.id === "timeline") && (
        <TabPanel id="timeline" active={active} idPrefix="session-tab" keepMounted>
          <div className="stack">
            <section className="chart-card" aria-labelledby="timeline-heading">
              <h2 id="timeline-heading">Observable timeline</h2>
              {timeline.length ? (
                <>
                  <div role="img" aria-label={`Area chart of observable participation, visual orientation and possible fatigue over ${timeline.length} samples. The same values are listed in the table below.`}>
                    <ResponsiveContainer width="100%" height={300}>
                      <AreaChart data={timeline}>
                        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                        <XAxis dataKey="timestamp" stroke="var(--text-muted)" /><YAxis domain={[0, 100]} stroke="var(--text-muted)" /><Tooltip /><Legend />
                        <Area dataKey="engagement" name="Observable participation" stroke="var(--chart-2)" fill="var(--chart-2)" fillOpacity={0.15} isAnimationActive={false} />
                        <Area dataKey="attention" name="Visual orientation" stroke="var(--chart-1)" fill="transparent" strokeDasharray="6 3" isAnimationActive={false} />
                        <Area dataKey="fatigue" name="Possible fatigue" stroke="var(--chart-3)" fill="transparent" strokeDasharray="2 3" isAnimationActive={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                  <details style={{ marginTop: 12 }}>
                    <summary>Show timeline as a table</summary>
                    <div className="table-scroll">
                      <table className="data-table">
                        <caption className="sr-only">Timeline samples (first 100)</caption>
                        <thead><tr><th scope="col" className="num">Time (s)</th><th scope="col" className="num">Anonymous occupancy</th><th scope="col" className="num">Observable participation</th><th scope="col" className="num">Visual orientation</th><th scope="col" className="num">Possible fatigue</th></tr></thead>
                        <tbody>{timeline.slice(0, 100).map((row) => <tr key={row.timestamp}><th scope="row" className="num">{Number(row.timestamp).toFixed(1)}</th><td className="num">{row.student_count ?? "—"}</td><td className="num">{row.engagement ?? "—"}</td><td className="num">{row.attention ?? "—"}</td><td className="num">{row.fatigue ?? "—"}</td></tr>)}</tbody>
                      </table>
                    </div>
                    {timeline.length > 100 && <p className="muted">Showing the first 100 of {timeline.length} samples.</p>}
                  </details>
                </>
              ) : <div className="empty">No timeline observations.</div>}
            </section>
            <section className="table-card" aria-labelledby="events-heading">
              <h2 id="events-heading">Events ({events.length})</h2>
              {!canReview && events.length > 0 && <p className="muted">Your role can view events but not review them.</p>}
              {events.length ? events.slice(0, 50).map((event: any) => (canReview ? <EventReviewRow key={event.id} event={event} onSaved={load} /> : <ReadOnlyEvent key={event.id} event={event} />)) : <div className="empty">No events detected.</div>}
              {events.length > 50 && <p className="muted">Showing the first 50 of {events.length} events.</p>}
            </section>
          </div>
        </TabPanel>
      )}

      {mounted.has("evidence") && tabs.some((t) => t.id === "evidence") && (
        <TabPanel id="evidence" active={active} idPrefix="session-tab" keepMounted>
          <div className="stack">
            <section className="table-card table-scroll" aria-labelledby="evidence-heading">
              <table className="data-table">
                <caption id="evidence-heading">Evidence by metric</caption>
                <thead><tr><th scope="col">Metric</th><th scope="col" className="num">Value</th><th scope="col">Availability</th><th scope="col">Reason</th><th scope="col" className="num">Coverage</th><th scope="col" className="num">Confidence</th><th scope="col" className="num">Valid</th><th scope="col" className="num">Total</th></tr></thead>
                <tbody>
                  {CANONICAL_METRICS.map(([key, kind, noun]) => {
                    const metric = summary.metric_results?.[key];
                    return (
                      <tr key={key}>
                        <th scope="row" data-th="Metric">{METRIC_LABELS[key] ?? key}</th>
                        <td className="num" data-th="Value">{metric?.available && metric.value != null ? formatMetricAvailability({ ...metric, coverage: null, confidence: null }, { kind, noun }) : "—"}</td>
                        <td data-th="Availability">{availabilityText(metric)}</td>
                        <td data-th="Reason">{metric?.available ? "—" : readableReason(metric?.reason)}</td>
                        <td className="num" data-th="Coverage">{metric?.coverage != null ? `${Math.round(metric.coverage * 100)}%` : "—"}</td>
                        <td className="num" data-th="Confidence">{metric?.confidence != null ? `${Math.round(metric.confidence * 100)}%` : "—"}</td>
                        <td className="num" data-th="Valid">{metric?.valid_observations ?? 0}</td>
                        <td className="num" data-th="Total">{metric?.total_observations ?? 0}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
            <section className="table-card" aria-labelledby="frame-heading">
              <h2 id="frame-heading">Frame quality</h2>
              <div className="summary-grid">
                <article><small>Overall quality</small><b>{quality?.overall_quality != null ? `${quality.overall_quality}/100` : "Unavailable"}</b><span>{quality?.status ?? "UNAVAILABLE"}</span></article>
                <article><small>Lighting</small><b>{lighting}</b><span>{brightness != null ? `Mean brightness ${brightness.toFixed(0)}/255` : "No brightness data"}</span></article>
                <article><small>Sharpness</small><b>{sharpness}</b><span>{blur != null ? `Mean sharpness score ${blur.toFixed(0)}` : "No sharpness data"}</span></article>
                <article><small>Frame-quality metric</small><b style={{ fontSize: 14 }}>{formatMetricAvailability(quality?.frame_quality)}</b></article>
              </div>
              {(quality?.warnings ?? []).length > 0 ? <ul>{quality.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul> : <p className="muted">No quality warnings were recorded.</p>}
            </section>
            <section className="table-card"><AudioStatus capabilities={capabilities} sessionAudio={audio} /></section>
            <SessionIntelligence sessionId={id!} onLoaded={(data) => setAudio(data.audio)} />
          </div>
        </TabPanel>
      )}

      {mounted.has("regions") && tabs.some((t) => t.id === "regions") && (
        <TabPanel id="regions" active={active} idPrefix="session-tab" keepMounted>
          <section className="table-card" aria-labelledby="regions-heading">
            <h2 id="regions-heading">Region analytics</h2>
            {regions?.status === "CALIBRATED" && regions.regions?.length ? (
              <>
                <p className="muted">Calibrated layout #{regions.layout_id} · version {regions.layout_version}. Counts are anonymous, session-local tracks per region.</p>
                <div className="table-scroll">
                  <table className="data-table">
                    <caption className="sr-only">Anonymous tracks and observations per region</caption>
                    <thead><tr><th scope="col">Region</th><th scope="col" className="num">Unique tracks</th><th scope="col" className="num">Observations</th><th scope="col" className="num">Raised-hand observations</th><th scope="col" className="num">Visual coverage</th></tr></thead>
                    <tbody>{regions.regions.map((r: any) => <tr key={r.region_id}><th scope="row" data-th="Region">{r.name}</th><td className="num" data-th="Unique tracks">{r.estimated_unique_tracks}</td><td className="num" data-th="Observations">{r.observation_count}</td><td className="num" data-th="Raised-hand observations">{r.raised_hand_observations}</td><td className="num" data-th="Visual coverage">{r.visual_coverage != null ? `${r.visual_coverage}%` : "Unavailable"}</td></tr>)}</tbody>
                  </table>
                </div>
              </>
            ) : (
              <EmptyState title="No calibrated region evidence" description={regions?.label || "No calibrated region evidence. Configure a classroom layout to enable region-aware analytics."} action={canManage ? <Link className="button secondary" to="/classroom-setup">Open classroom setup</Link> : undefined} />
            )}
          </section>
        </TabPanel>
      )}

      {mounted.has("artifacts") && tabs.some((t) => t.id === "artifacts") && (
        <TabPanel id="artifacts" active={active} idPrefix="session-tab" keepMounted>
          <div className="stack">
            <section className="table-card" aria-labelledby="artifacts-heading">
              <h2 id="artifacts-heading">Stored artifacts</h2>
              <p className="muted">Only files that exist on the server are listed. Downloads are authorized with your account.</p>
              <ArtifactList artifacts={artifacts} emptyText={session.status === "COMPLETED" ? "No stored artifacts were found for this session (they may have been deleted)." : "Artifacts appear when processing completes."} />
            </section>
            {canManage && artifacts.length > 0 && (
              <section className="table-card" aria-labelledby="delete-artifacts-heading">
                <h2 id="delete-artifacts-heading">Delete stored files</h2>
                <p className="muted">Removes the selected files permanently. Analytics evidence (metrics, events, timeline) is kept. This action is audited.</p>
                <fieldset style={{ border: 0, padding: 0, margin: 0 }} disabled={ACTIVE.has(session.status)}>
                  <legend className="sr-only">Artifact types to delete</legend>
                  <div className="actions">{DELETABLE_KINDS.map(([kind, text]) => <label key={kind} className="chip"><input type="checkbox" checked={kinds.includes(kind)} onChange={(e) => setKinds((old) => (e.target.checked ? [...old, kind] : old.filter((k) => k !== kind)))} /> {text}</label>)}</div>
                </fieldset>
                <button className="button danger" style={{ marginTop: 12 }} disabled={kinds.length === 0 || ACTIVE.has(session.status)} onClick={() => setConfirmArtifacts(true)}>Delete selected files…</button>
              </section>
            )}
          </div>
        </TabPanel>
      )}

      <TabPanel id="notes" active={active} idPrefix="session-tab" keepMounted={mounted.has("notes")}>
        <section className="table-card" aria-labelledby="notes-heading"><h2 id="notes-heading">Collaboration notes</h2><SessionNotes sessionId={id!} /></section>
      </TabPanel>

      <ConfirmDialog open={confirmDelete} title="Delete this session?" description={`This permanently deletes "${session.name}", all of its evidence, reports and stored videos. This cannot be undone and is recorded in the audit trail.`} confirmLabel="Delete session" requireText="DELETE" onConfirm={() => void remove()} onCancel={() => setConfirmDelete(false)} />
      <ConfirmDialog open={confirmArtifacts} title="Delete selected files?" description={`Permanently delete: ${kinds.map((k) => DELETABLE_KINDS.find(([kind]) => kind === k)?.[1]).join(", ")}. Analytics evidence is kept.`} confirmLabel="Delete files" requireText="DELETE" onConfirm={() => void removeArtifacts()} onCancel={() => setConfirmArtifacts(false)} />
    </>
  );
}
