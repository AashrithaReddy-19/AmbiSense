/* eslint-disable react-hooks/set-state-in-effect -- the drawer loads its own evidence whenever a different report is opened */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArtifactList, type Artifact } from "./ArtifactList";
import { MetricValue } from "./MetricValue";
import { PrivacyNotice } from "./PrivacyNotice";
import { ErrorState, LoadingSkeleton } from "./States";
import { StatusBadge } from "./StatusBadge";
import { METRIC_LABELS, apiProblem, contextLabel, formatDateTime, formatDuration, type ApiProblem } from "../constants";
import { api } from "../services/api";

const DETAIL_METRICS: Array<[string, "percent" | "count", string | undefined]> = [
  ["occupancy", "count", "people"], ["peak_occupancy", "count", "people"], ["unoccupied_capacity", "count", "seats"],
  ["visual_orientation", "percent", undefined], ["observable_participation", "percent", undefined], ["prolonged_eye_closure", "count", "events"],
  ["possible_fatigue", "percent", undefined], ["yawning", "count", "events"], ["raised_hands", "count", "events"], ["frame_quality", "percent", undefined],
];

export const REPORT_METHODOLOGY = "Anonymous person detection and session-local tracking (YOLOv8 + ByteTrack); face and pose landmarks (MediaPipe) when the models are available. Metrics are aggregated per interval; each value carries its coverage, confidence and the number of valid observations, and is reported as unavailable — never zero — when evidence is missing.";
export const REPORT_LIMITATIONS = [
  "Estimates depend on camera angle, lighting and occlusion; people can be missed or double-counted.",
  "Head direction and eye/mouth landmarks are not measures of attention, comprehension or wellbeing.",
  "Values are aggregate and anonymous; they cannot and must not be traced to individual students.",
];

/** Everything shown here comes from JSON endpoints; the PDF is only offered as a download, never parsed. */
export function ReportDetails({ report, classroomName, courseName }: { report: any; classroomName: string; courseName: string }) {
  const sessionId: number = report.session_id;
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [summary, setSummary] = useState<any>(null);
  const [quality, setQuality] = useState<any>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [partial, setPartial] = useState<string[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState("loading"); setPartial([]);
    Promise.allSettled([api.get(`/sessions/${sessionId}/analytics`), api.get(`/v1/sessions/${sessionId}/quality`), api.get(`/v1/sessions/${sessionId}/artifacts`)]).then(([analytics, evidence, files]) => {
      if (cancelled) return;
      const missing: string[] = [];
      if (analytics.status === "fulfilled") setSummary(analytics.value.data); else missing.push("metrics");
      if (evidence.status === "fulfilled") setQuality(evidence.value.data); else missing.push("evidence quality");
      if (files.status === "fulfilled") setArtifacts(files.value.data?.artifacts ?? []); else missing.push("artifacts");
      if (analytics.status === "rejected" && evidence.status === "rejected" && files.status === "rejected") {
        setProblem(apiProblem(analytics.reason, "Report details could not be loaded.")); setState("error");
      } else { setPartial(missing); setState("ok"); }
    });
    return () => { cancelled = true; };
  }, [sessionId, reloadKey]);

  return (
    <div className="stack">
      <section aria-labelledby="rd-meta">
        <h3 id="rd-meta">Session</h3>
        <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "6px 16px", margin: 0 }}>
            <dt>Name</dt><dd>{report.name}</dd>
            <dt>Source</dt><dd>{report.source_type === "LIVE" ? `Live session · ${report.name}` : report.source_filename || "Uploaded video"}</dd>
            <dt>Status</dt><dd><StatusBadge status={report.status} /></dd>
            <dt>Data source</dt><dd>{report.is_test ? "TEST" : report.analytics_mode}</dd>
            <dt>Activity</dt><dd>{contextLabel(report.activity_context ?? "LECTURE")}</dd>
            <dt>Classroom</dt><dd>{classroomName}</dd>
            <dt>Course</dt><dd>{courseName}</dd>
            <dt>Created</dt><dd>{formatDateTime(report.created_at)}</dd>
            <dt>Duration</dt><dd>{formatDuration(report.duration)}</dd>
        </dl>
        <p style={{ marginBottom: 0 }}><Link to={`/sessions/${sessionId}`}>Open full session</Link></p>
      </section>

      {state === "loading" && <LoadingSkeleton kind="card" count={2} />}
      {state === "error" && <ErrorState message={problem?.message ?? "Report details could not be loaded."} code={problem?.requestId} onRetry={() => setReloadKey((n) => n + 1)} />}
      {state === "ok" && partial.length > 0 && <div className="banner warning" role="status">Some details could not be loaded: {partial.join(", ")}. Available sections are shown below.</div>}

      {state === "ok" && summary && (
        <section aria-labelledby="rd-metrics">
          <h3 id="rd-metrics">Metrics</h3>
          <div className="live-metrics">
            {DETAIL_METRICS.map(([key, kind, noun]) => <MetricValue key={key} metric={summary.metric_results?.[key]} kind={kind} noun={noun} label={METRIC_LABELS[key] ?? key} />)}
          </div>
        </section>
      )}

      {state === "ok" && quality && (
        <section aria-labelledby="rd-quality">
          <h3 id="rd-quality">Evidence quality</h3>
          <p>Overall quality: <b>{quality.status ?? "UNAVAILABLE"}</b>{quality.overall_quality != null && ` (${quality.overall_quality}/100)`}</p>
          {(quality.warnings ?? []).length > 0 && <ul>{quality.warnings.map((warning: string) => <li key={warning}>{warning}</li>)}</ul>}
        </section>
      )}

      <section aria-labelledby="rd-method"><h3 id="rd-method">Methodology</h3><p>{REPORT_METHODOLOGY}</p></section>
      <PrivacyNotice showValidation />
      <section aria-labelledby="rd-limits"><h3 id="rd-limits">Limitations</h3><ul>{REPORT_LIMITATIONS.map((text) => <li key={text}>{text}</li>)}</ul></section>

      {state === "ok" && (
        <section aria-labelledby="rd-artifacts">
          <h3 id="rd-artifacts">Downloads</h3>
          <ArtifactList artifacts={artifacts} emptyText={report.status === "COMPLETED" ? "No stored artifacts were found on disk for this session." : "Artifacts become available when processing completes."} />
        </section>
      )}
    </div>
  );
}
