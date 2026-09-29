import { ShieldCheck } from "lucide-react";
import { metricDefinition } from "../content/metricDefinitions";
import { readableReason } from "./MetricValue";

/** The exact statements required wherever evidence is shown. Kept in one place so wording never drifts. */
export const NOTICE_ANONYMOUS = "AmbiSense uses anonymous session-local tracking and does not identify students.";
export const NOTICE_OCCUPANCY = "Occupancy is an estimate and is not verified attendance.";
export const NOTICE_HIGH_IMPACT = "These observational indicators must not be used as the sole basis for grading, discipline, attendance, or other high-impact decisions.";
export const NOTICE_NOT_VALIDATED = "Not validated on real classroom footage.";
export const NOTICE_NO_ACCURACY = "No verified accuracy or fairness result is currently available.";

/** `full` shows all three privacy statements; `compact` collapses them into one line with a details toggle. */
export function PrivacyNotice({ variant = "full", showValidation = false }: { variant?: "full" | "compact"; showValidation?: boolean }) {
  if (variant === "compact") {
    return (
      <div className="notice privacy-notice" role="note">
        <ShieldCheck size={15} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 6 }} />
        {NOTICE_ANONYMOUS} {NOTICE_OCCUPANCY}
        <details style={{ marginTop: 6 }}>
          <summary>Responsible use</summary>
          <p style={{ margin: "6px 0 0" }}>{NOTICE_HIGH_IMPACT}</p>
          {showValidation && <p style={{ margin: "6px 0 0" }}>{NOTICE_NOT_VALIDATED} {NOTICE_NO_ACCURACY}</p>}
        </details>
      </div>
    );
  }
  return (
    <div className="notice privacy-notice" role="note" aria-label="Privacy and responsible use">
      <b><ShieldCheck size={15} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 6 }} />Privacy and responsible use</b>
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        <li>{NOTICE_ANONYMOUS}</li>
        <li>{NOTICE_OCCUPANCY}</li>
        <li>{NOTICE_HIGH_IMPACT}</li>
        {showValidation && <li>{NOTICE_NOT_VALIDATED} {NOTICE_NO_ACCURACY}</li>}
      </ul>
    </div>
  );
}

/** Expandable definition of one metric: meaning, required evidence, coverage, confidence, failure reasons, limitations, contexts. */
export function MetricExplainer({ metric }: { metric: string }) {
  const definition = metricDefinition(metric);
  if (!definition) return null;
  return (
    <details className="metric-explainer">
      <summary>What does “{definition.label}” mean?</summary>
      <dl>
        <dt>Meaning</dt><dd>{definition.meaning}</dd>
        <dt>Required evidence</dt><dd>{definition.requiredEvidence}</dd>
        <dt>Coverage</dt><dd>{definition.coverage}</dd>
        <dt>Confidence</dt><dd>{definition.confidence}</dd>
        <dt>Why it can be unavailable</dt>
        <dd><ul>{definition.failureReasons.map((reason) => <li key={reason}>{readableReason(reason)}</li>)}</ul></dd>
        <dt>Limitations</dt><dd><ul>{definition.limitations.map((text) => <li key={text}>{text}</li>)}</ul></dd>
        <dt>Activity contexts</dt><dd>{definition.contexts}</dd>
      </dl>
    </details>
  );
}
