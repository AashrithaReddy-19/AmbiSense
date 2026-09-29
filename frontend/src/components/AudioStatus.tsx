import { StatusBadge } from "./StatusBadge";

export type AudioState = "DISABLED" | "NOT_CONFIGURED" | "MODEL_UNAVAILABLE" | "READY" | "PROCESSING" | "COMPLETED" | "FAILED";

export const AUDIO_STATE_LABEL: Record<AudioState, string> = {
  DISABLED: "Disabled", NOT_CONFIGURED: "Not configured", MODEL_UNAVAILABLE: "Model unavailable", READY: "Ready", PROCESSING: "Processing", COMPLETED: "Completed", FAILED: "Failed",
};

const STATE_TONE: Record<AudioState, string> = { DISABLED: "STOPPED", NOT_CONFIGURED: "STOPPED", MODEL_UNAVAILABLE: "INSUFFICIENT_EVIDENCE", READY: "AVAILABLE", PROCESSING: "PROCESSING", COMPLETED: "COMPLETED", FAILED: "FAILED" };

/**
 * One truthful state for optional audio. Capability wins first (a disabled or unavailable feature is never
 * shown as operational); only when the feature is usable does the per-session result decide between
 * Ready / Processing / Completed / Failed.
 */
export function audioState(capabilities: { status?: string } | null | undefined, sessionAudio?: { status?: string } | null): AudioState {
  const capability = capabilities?.status;
  if (capability === "DISABLED") return "DISABLED";
  if (capability === "NOT_CONFIGURED") return "NOT_CONFIGURED";
  if (capability === "MODEL_UNAVAILABLE") return "MODEL_UNAVAILABLE";
  const status = sessionAudio?.status;
  if (status === "FAILED") return "FAILED";
  if (status === "PROCESSING" || status === "PENDING" || status === "RUNNING") return "PROCESSING";
  if (status === "AVAILABLE" || status === "COMPLETED" || status === "RETENTION_DELETED") return "COMPLETED";
  return capability === "READY" ? "READY" : "NOT_CONFIGURED";
}

export function AudioStatus({ capabilities, sessionAudio }: { capabilities: any; sessionAudio?: any }) {
  const state = audioState(capabilities, sessionAudio);
  const transcription = capabilities?.transcription, diarization = capabilities?.diarization;
  return (
    <section aria-labelledby="audio-status-heading">
      <h3 id="audio-status-heading">Optional audio analysis</h3>
      <p style={{ margin: "0 0 8px" }}><StatusBadge status={STATE_TONE[state]} label={AUDIO_STATE_LABEL[state]} /></p>
      <p className="muted" style={{ margin: "0 0 8px" }}>
        {capabilities?.reason ?? "Audio capability could not be determined."}
        {state === "COMPLETED" && sessionAudio?.status === "RETENTION_DELETED" ? " Raw audio and transcript were removed by the retention policy; aggregates are preserved." : ""}
        {state === "FAILED" ? " Visual analytics for this session are not affected." : ""}
      </p>
      {capabilities && (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          <li>Audio processing: {capabilities.audio_processing_enabled ? "enabled" : "disabled"}{capabilities.audio_processing_enabled && !capabilities.ffmpeg_available ? " (FFmpeg not found)" : ""}</li>
          <li>Transcription: {transcription?.configured ? `${transcription.provider} configured` : "no adapter configured"}{transcription?.configured ? `, model ${transcription.model_available ? "available" : "unavailable"}` : ""}</li>
          <li>Speaker separation: {diarization?.configured ? `${diarization.provider} configured, model ${diarization.model_available ? "available" : "unavailable"}` : "not configured"}</li>
        </ul>
      )}
      <p className="muted" style={{ marginBottom: 0 }}>Speakers appear only as anonymous roles; no speaker is ever identified.</p>
    </section>
  );
}
