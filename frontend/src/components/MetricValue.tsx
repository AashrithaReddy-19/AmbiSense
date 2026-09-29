import type { MetricAvailability, MetricReason } from "../types";

const REASON_TEXT: Record<MetricReason, string> = {
  no_observations: "no observations were recorded",
  insufficient_valid_observations: "not enough valid observations were available",
  no_person_detected: "no one was detected in frame",
  facial_landmarks_unavailable: "facial landmarks were not detected",
  pose_landmarks_unavailable: "pose landmarks were not detected",
  poor_frame_quality: "frame quality was too low",
  low_light: "lighting was too low",
  excessive_blur: "the video was too blurred",
  face_occluded: "the face was occluded",
  model_unavailable: "the required model is unavailable",
  inference_failed: "analysis failed for this observation",
  not_applicable_for_activity: "this metric does not apply to the current activity",
  processing_incomplete: "processing has not finished yet",
  legacy_data_without_evidence: "this session predates evidence tracking for this metric",
};

/** Human-readable explanation for a reason code. Falls back to a generic,
 * still-honest message for any code this build does not recognize, so an
 * older frontend never crashes or silently blanks out against a newer
 * backend reason. */
export function readableReason(reason: string | null | undefined): string {
  if (!reason) return "no reason was provided";
  return REASON_TEXT[reason as MetricReason] ?? "this metric is currently unavailable";
}

export type MetricValueKind = "percent" | "count";

/** Format one MetricAvailability into the display text used across the
 * live classroom, session detail, and report pages. Never converts a
 * missing value into 0, and never renders "-%". */
export function formatMetricAvailability(
  metric: MetricAvailability | null | undefined,
  { kind = "percent", noun }: { kind?: MetricValueKind; noun?: string } = {},
): string {
  if (!metric) return "Unavailable";
  if (!metric.available || metric.value == null) {
    const observed = metric.total_observations > 0;
    const prefix = observed && metric.reason === "insufficient_valid_observations"
      ? `Insufficient evidence — ${metric.valid_observations} of ${metric.total_observations} observations were valid`
      : `Unavailable — ${readableReason(metric.reason)}`;
    return prefix;
  }
  const valueText = kind === "percent" ? `${metric.value}%` : `${metric.value}${noun ? ` ${noun}` : ""}`;
  const parts = [valueText];
  if (metric.coverage != null) parts.push(`Coverage ${Math.round(metric.coverage * 100)}%`);
  if (metric.confidence != null) parts.push(`Confidence ${Math.round(metric.confidence * 100)}%`);
  return parts.join(" · ");
}

export function MetricValue({
  metric, kind = "percent", noun, label,
}: { metric: MetricAvailability | null | undefined; kind?: MetricValueKind; noun?: string; label: string }) {
  const text = formatMetricAvailability(metric, { kind, noun });
  const available = Boolean(metric?.available);
  return (
    <article className="metric" title={metric?.reason ? readableReason(metric.reason) : undefined}>
      <small>{label}</small>
      <b className={available ? undefined : "unavailable"}>{text}</b>
    </article>
  );
}
