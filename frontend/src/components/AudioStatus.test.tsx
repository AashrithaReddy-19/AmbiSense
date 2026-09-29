// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AUDIO_STATE_LABEL, AudioStatus, audioState } from "./AudioStatus";

afterEach(cleanup);
const capability = (status: string, extra: Record<string, unknown> = {}) => ({ status, reason: `capability ${status}`, audio_processing_enabled: status !== "DISABLED", ffmpeg_available: status !== "MODEL_UNAVAILABLE", transcription: { configured: status === "READY", provider: status === "READY" ? "FASTER_WHISPER" : "NONE", model_available: status === "READY", model: "base" }, diarization: { configured: false, provider: "NONE", model_available: false }, ...extra });

describe("audioState", () => {
  it("never reports a disabled, unconfigured or unavailable capability as operational, whatever the session says", () => {
    for (const status of ["DISABLED", "NOT_CONFIGURED", "MODEL_UNAVAILABLE"]) expect(audioState(capability(status), { status: "AVAILABLE" })).toBe(status);
  });
  it("maps per-session results only when the capability is ready", () => {
    const ready = capability("READY");
    expect(audioState(ready, null)).toBe("READY");
    expect(audioState(ready, { status: "NOT_PROCESSED" })).toBe("READY");
    expect(audioState(ready, { status: "PROCESSING" })).toBe("PROCESSING");
    expect(audioState(ready, { status: "AVAILABLE" })).toBe("COMPLETED");
    expect(audioState(ready, { status: "RETENTION_DELETED" })).toBe("COMPLETED");
    expect(audioState(ready, { status: "FAILED" })).toBe("FAILED");
  });
  it("falls back to Not configured when the capability is unknown", () => {
    expect(audioState(null, null)).toBe("NOT_CONFIGURED");
  });
  it("covers the seven required states", () => {
    expect(Object.values(AUDIO_STATE_LABEL)).toEqual(["Disabled", "Not configured", "Model unavailable", "Ready", "Processing", "Completed", "Failed"]);
  });
});

describe("AudioStatus", () => {
  it.each([["DISABLED", "Disabled"], ["NOT_CONFIGURED", "Not configured"], ["MODEL_UNAVAILABLE", "Model unavailable"], ["READY", "Ready"]])("renders the %s capability as “%s”", (status, label) => {
    render(<AudioStatus capabilities={capability(status)} />);
    expect(screen.getByText(label)).toBeTruthy();
    expect(screen.getByText(`capability ${status}`)).toBeTruthy();
  });
  it("shows processing, completed and failed session states with honest notes", () => {
    const ready = capability("READY");
    const { rerender } = render(<AudioStatus capabilities={ready} sessionAudio={{ status: "PROCESSING" }} />);
    expect(screen.getByText("Processing")).toBeTruthy();
    rerender(<AudioStatus capabilities={ready} sessionAudio={{ status: "RETENTION_DELETED" }} />);
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText(/removed by the retention policy; aggregates are preserved/)).toBeTruthy();
    rerender(<AudioStatus capabilities={ready} sessionAudio={{ status: "FAILED" }} />);
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText(/Visual analytics for this session are not affected/)).toBeTruthy();
  });
  it("lists transcription and speaker separation truthfully and never claims speaker identity", () => {
    render(<AudioStatus capabilities={capability("READY", { diarization: { configured: true, provider: "LOCAL_ADAPTER", model_available: false } })} />);
    expect(screen.getByText(/Transcription: FASTER_WHISPER configured, model available/)).toBeTruthy();
    expect(screen.getByText(/Speaker separation: LOCAL_ADAPTER configured, model unavailable/)).toBeTruthy();
    expect(screen.getByText(/anonymous roles; no speaker is ever identified/)).toBeTruthy();
  });
  it("warns when audio is enabled but FFmpeg is missing", () => {
    render(<AudioStatus capabilities={capability("MODEL_UNAVAILABLE", { audio_processing_enabled: true, ffmpeg_available: false })} />);
    expect(screen.getByText(/Audio processing: enabled \(FFmpeg not found\)/)).toBeTruthy();
  });
});
