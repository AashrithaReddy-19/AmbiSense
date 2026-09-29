import { AlertCircle, CheckCircle2, Clock, HelpCircle, Loader2, XCircle } from "lucide-react";

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
  COMPLETED: "success", AVAILABLE: "success", HIGH: "success",
  PROCESSING: "info", INITIALIZING: "info", FINALIZING: "info", DECODING: "info", AGGREGATING: "info", GENERATING_REPORT: "info", MODERATE: "info",
  QUEUED: "neutral", CREATED: "neutral", STOPPED: "neutral",
  FAILED: "danger", LOW: "warning", INSUFFICIENT_EVIDENCE: "warning",
};
const TONE_ICON = { success: CheckCircle2, warning: AlertCircle, danger: XCircle, info: Loader2, neutral: Clock } as const;

/** Status is never communicated by color alone: each tone pairs with a
 * distinct icon shape, and the label text is always rendered. */
export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const tone = STATUS_TONE[status?.toUpperCase()] ?? "neutral";
  const Icon = TONE_ICON[tone];
  return (
    <span className={`badge badge-${tone}`}>
      <Icon size={12} aria-hidden="true" />
      {label ?? status.replace(/_/g, " ")}
    </span>
  );
}

const QUALITY_TONE: Record<string, "success" | "info" | "warning" | "danger" | "neutral"> = {
  HIGH: "success", MODERATE: "info", LOW: "warning", INSUFFICIENT_EVIDENCE: "danger",
};

export function QualityBadge({ tier }: { tier: string | null | undefined }) {
  if (!tier) return <span className="badge badge-neutral"><HelpCircle size={12} aria-hidden="true" />Unavailable</span>;
  const tone = QUALITY_TONE[tier.toUpperCase()] ?? "neutral";
  const Icon = TONE_ICON[tone];
  const text = tier === "INSUFFICIENT_EVIDENCE" ? "Insufficient evidence" : tier.charAt(0) + tier.slice(1).toLowerCase();
  return <span className={`badge badge-${tone}`}><Icon size={12} aria-hidden="true" />{text}</span>;
}
