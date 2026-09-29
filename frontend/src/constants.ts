/** Canonical option lists shared by every page. They mirror backend values exactly
 * (backend/app/services/activity_context.py:ACTIVITY_CONTEXTS, data-source semantics
 * in backend/app/main.py:_apply_data_source) so filters never send a value the API rejects. */
export const ACTIVITY_CONTEXTS = ["LECTURE", "EXAMINATION", "GROUP_DISCUSSION", "LABORATORY", "STUDENT_PRESENTATION", "INDEPENDENT_WRITING", "READING", "VIDEO_SCREENING", "BREAK"] as const;

export const DATA_SOURCES = [
  { value: "REAL", label: "Real only" },
  { value: "DEMO", label: "Demo only" },
  { value: "TEST", label: "Test only" },
  { value: "ALL", label: "All data" },
] as const;
export type DataSource = (typeof DATA_SOURCES)[number]["value"];

/** Preferred, non-judgemental metric names. Never "attentive", "disengaged", "attendance", etc. */
export const METRIC_LABELS: Record<string, string> = {
  observable_participation: "Observable participation indicator",
  visual_orientation: "Visual-orientation estimate",
  possible_fatigue: "Possible fatigue indicator",
  occupancy: "Anonymous occupancy estimate",
  peak_occupancy: "Peak anonymous occupancy",
  unoccupied_capacity: "Estimated unoccupied capacity",
  prolonged_eye_closure: "Possible prolonged eye closure",
  yawning: "Yawning observation",
  raised_hands: "Raised-hand observation",
  frame_quality: "Frame quality",
  camera_quality: "Camera quality",
  audio_quality: "Audio quality",
  question_count: "Question count",
  fusion: "Fused evidence estimate",
};

export const TREND_METRICS = ["observable_participation", "visual_orientation", "possible_fatigue", "occupancy", "frame_quality", "camera_quality"] as const;

export const label = (value: string | null | undefined) => (value ? value.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : "—");
export const contextLabel = (value: string) => value.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

export type ApiProblem = { message: string; code?: string; status?: number; requestId?: string; details?: unknown };

/** Normalise any axios/API failure into one shape, preferring the canonical `error` contract,
 * then legacy `detail` (string, structured or validation array), then a generic fallback. */
export function apiProblem(error: unknown, fallback = "The request could not be completed."): ApiProblem {
  const response = (error as { response?: { status?: number; data?: any } })?.response;
  if (!response) return { message: (error as Error)?.message && !/^Request failed/.test((error as Error).message) ? (error as Error).message : fallback };
  const data = response.data ?? {};
  const canonical = data.error;
  if (canonical?.message) return { message: canonical.message, code: canonical.code, status: response.status, requestId: canonical.request_id, details: canonical.details };
  const detail = data.detail;
  if (typeof detail === "string") return { message: detail, status: response.status };
  if (detail?.error?.message) return { message: detail.error.message, code: detail.error.code, status: response.status };
  if (Array.isArray(detail) && detail[0]?.msg) return { message: detail.map((item: any) => item.msg).join("; "), code: "VALIDATION_FAILED", status: response.status };
  return { message: fallback, status: response.status };
}

export const isForbidden = (problem: ApiProblem) => problem.status === 403;

export function formatDateTime(value: string | number | Date | null | undefined): string {
  if (!value) return "—";
  const date = new Date(typeof value === "string" && !/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? `${value}Z` : value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

export const percent = (value: number | null | undefined, digits = 0): string => (value == null || !Number.isFinite(value) ? "Unavailable" : `${(value * 100).toFixed(digits)}%`);

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
