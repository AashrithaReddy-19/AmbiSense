import { Download, FileText, Film } from "lucide-react";
import { apiProblem, formatBytes } from "../constants";
import { downloadFile, useInFlight } from "../services/download";
import { useToast } from "./Toast";

export type Artifact = { kind: string; label: string; filename: string; size_bytes: number; media_type: string; url: string };

/**
 * Lists only artifacts the API confirmed exist. Downloads go through axios (bearer token sent,
 * errors surfaced as toasts) and a second click while one is in flight is ignored.
 */
export function ArtifactList({ artifacts, emptyText = "No stored artifacts are available for this session." }: { artifacts: Artifact[]; emptyText?: string }) {
  const { show } = useToast();
  const { run, busy } = useInFlight();
  if (artifacts.length === 0) return <p className="muted">{emptyText}</p>;
  async function download(artifact: Artifact) {
    show(`Downloading ${artifact.label}…`, "info");
    await run(artifact.kind, async () => {
      try { await downloadFile(artifact.url, artifact.filename); show(`${artifact.label} downloaded.`, "success"); }
      catch (error) { show(apiProblem(error, `${artifact.label} could not be downloaded.`).message, "error"); }
    });
  }
  return (
    <ul className="match-list">
      {artifacts.map((artifact) => {
        const Icon = artifact.media_type.startsWith("video") ? Film : FileText;
        return (
          <li className="match-card" key={artifact.kind} style={{ gridTemplateColumns: "1fr auto", alignItems: "center" }}>
            <div>
              <b><Icon size={15} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />{artifact.label}</b>
              <div className="muted">{artifact.filename} · {formatBytes(artifact.size_bytes)}</div>
            </div>
            <button className="button secondary small" disabled={busy(artifact.kind)} onClick={() => void download(artifact)} aria-label={`Download ${artifact.label}`}>
              <Download size={14} /> {busy(artifact.kind) ? "Downloading…" : "Download"}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
