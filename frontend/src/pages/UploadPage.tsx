import { AlertTriangle, CheckCircle2, CloudUpload, Download, Film, RotateCcw, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useToast } from "../components/Toast";
import { StatusBadge } from "../components/StatusBadge";
import { ErrorState } from "../components/States";
import { api } from "../services/api";

const ALLOWED_EXTENSIONS = [".mp4", ".avi", ".mov", ".mkv"];
const ALLOWED_MIME_TYPES = ["video/mp4", "video/quicktime", "video/x-msvideo", "video/avi", "video/x-matroska", "application/octet-stream"];
const ACTIVITY_CONTEXTS = ["LECTURE", "EXAMINATION", "GROUP_DISCUSSION", "LABORATORY", "STUDENT_PRESENTATION", "INDEPENDENT_WRITING", "READING", "VIDEO_SCREENING", "BREAK"];
const PROCESSING_STAGES = ["QUEUED", "INITIALIZING", "DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT", "COMPLETED"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
function formatDuration(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "Unavailable";
  const m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}
function readVideoDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    const cleanup = (value: number | null) => { URL.revokeObjectURL(url); resolve(value); };
    video.onloadedmetadata = () => cleanup(Number.isFinite(video.duration) ? video.duration : null);
    video.onerror = () => cleanup(null);
    video.src = url;
  });
}

export function UploadPage() {
  const { show } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [validationError, setValidationError] = useState("");
  const [name, setName] = useState("");
  const [classroomId, setClassroomId] = useState("");
  const [courseId, setCourseId] = useState("");
  const [activityContext, setActivityContext] = useState("LECTURE");
  const [consent, setConsent] = useState(false);
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [courses, setCourses] = useState<any[]>([]);
  const [limits, setLimits] = useState<{ max_upload_mb: number; max_video_duration_minutes: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [job, setJob] = useState<any>(null);
  const [message, setMessage] = useState("");
  const timer = useRef<number | null>(null);
  const generation = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get("/health").then((r) => setLimits(r.data)).catch(() => {});
    api.get("/v1/classrooms").then((r) => setClassrooms(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    api.get("/v1/courses").then((r) => setCourses(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  }, []);
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);

  function monitor(jobId: string) {
    if (timer.current) window.clearInterval(timer.current);
    const myGeneration = ++generation.current;
    const poll = async () => {
      try {
        const next = (await api.get(`/jobs/${jobId}`)).data;
        if (myGeneration !== generation.current) return; // a newer retry superseded this polling run
        setJob(next);
        if (["COMPLETED", "FAILED", "CANCELLED"].includes(next.status) && timer.current) {
          window.clearInterval(timer.current); timer.current = null;
          if (next.status === "COMPLETED") show("Processing completed.", "success");
          else if (next.status === "FAILED") show("Processing failed. See details below.", "error");
        }
      } catch (error: any) {
        if (myGeneration !== generation.current) return;
        if (error.response?.status === 401) {
          if (timer.current) { window.clearInterval(timer.current); timer.current = null; }
          setMessage("Your session expired. Sign in again to keep tracking this job.");
        }
        // Other failures are treated as temporary; the next tick retries automatically.
      }
    };
    void poll();
    timer.current = window.setInterval(poll, 1500);
  }

  function validate(candidate: File): string {
    const extension = `.${candidate.name.split(".").pop()?.toLowerCase() || ""}`;
    if (!ALLOWED_EXTENSIONS.includes(extension)) return `Unsupported file type. Use ${ALLOWED_EXTENSIONS.join(", ")}.`;
    if (candidate.type && !ALLOWED_MIME_TYPES.includes(candidate.type)) return "The selected file's type does not look like a supported video format.";
    if (candidate.size === 0) return "The selected file is empty.";
    if (limits && candidate.size > limits.max_upload_mb * 1024 * 1024) return `File exceeds the ${limits.max_upload_mb} MB upload limit.`;
    return "";
  }

  const selectFile = useCallback(async (candidate: File) => {
    const error = validate(candidate);
    setValidationError(error);
    setFile(error ? null : candidate);
    setDuration(null);
    setJob(null);
    setMessage("");
    if (!error) {
      setName((old) => old || candidate.name.replace(/\.[^.]+$/, ""));
      const seconds = await readVideoDuration(candidate);
      setDuration(seconds);
      if (seconds != null && limits && seconds > limits.max_video_duration_minutes * 60) {
        setValidationError(`Video duration exceeds the ${limits.max_video_duration_minutes}-minute limit.`);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limits]);

  function removeFile() {
    setFile(null); setDuration(null); setValidationError(""); setJob(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault(); setDragActive(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) void selectFile(dropped);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file || validationError || !consent) return;
    setBusy(true); setUploadProgress(0); setMessage(""); setJob(null);
    const data = new FormData();
    data.append("file", file);
    data.append("name", name || file.name);
    if (classroomId) data.append("classroom_id", classroomId);
    if (courseId) data.append("course_id", courseId);
    data.append("activity_context", activityContext);
    try {
      show("Upload started.", "info");
      const response = await api.post("/uploads", data, { onUploadProgress: (event) => setUploadProgress(event.total ? Math.round((event.loaded / event.total) * 100) : 0) });
      show(`Session #${response.data.id} accepted for processing.`, "success");
      setJob({ job_id: response.data.job_id, session_id: response.data.id, status: "QUEUED", stage: "QUEUED", progress: 0, processed_frames: 0, total_frames: response.data.total_frames });
      monitor(response.data.job_id);
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      const safeMessage = typeof detail === "string" ? detail : detail?.error?.message || "Upload failed. Check the file and try again.";
      setMessage(safeMessage);
      show(safeMessage, "error");
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!job?.job_id) return;
    try {
      await api.post(`/jobs/${job.job_id}/retry`);
      show("Processing retry requested.", "info");
      setJob((old: any) => ({ ...old, status: "QUEUED", stage: "QUEUED", error: null }));
      monitor(job.job_id);
    } catch (error: any) {
      show(error.response?.data?.detail || "Retry could not be started.", "error");
    }
  }

  function startOver() {
    removeFile();
    setName(""); setClassroomId(""); setCourseId(""); setActivityContext("LECTURE"); setConsent(false);
  }

  const stageIndex = job ? PROCESSING_STAGES.indexOf(job.stage || job.status) : -1;
  const isTerminal = job && ["COMPLETED", "FAILED", "CANCELLED"].includes(job.status);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Upload &amp; process a classroom video</h1>
          <p>Select a video, confirm consent, and queue it for anonymous, real classroom analytics.</p>
        </div>
      </div>

      <form className="upload-card" onSubmit={submit}>
        <h2 style={{ marginTop: 0 }}>1. Select video</h2>
        {!file ? (
          <div
            className="drop"
            role="button"
            tabIndex={0}
            aria-label="Choose a classroom video file, or drag and drop one here"
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); } }}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            onDrop={onDrop}
            style={dragActive ? { borderColor: "var(--primary)", background: "var(--surface-secondary)" } : undefined}
          >
            <CloudUpload size={42} aria-hidden="true" />
            <b>Drop a classroom recording here</b>
            <span>or click to browse · MP4, AVI, MOV, MKV{limits ? ` · up to ${limits.max_upload_mb} MB, ${limits.max_video_duration_minutes} minutes` : ""}</span>
            <input ref={inputRef} type="file" aria-label="Choose a classroom video file" accept={ALLOWED_EXTENSIONS.join(",")} onChange={(e) => { const picked = e.target.files?.[0]; if (picked) void selectFile(picked); }} />
          </div>
        ) : (
          <div className="session-meta" style={{ justifyContent: "space-between" }}>
            <span><Film size={16} style={{ verticalAlign: "-3px", marginRight: 6 }} aria-hidden="true" /><b>{file.name}</b></span>
            <span>Size: <b>{formatBytes(file.size)}</b></span>
            <span>Type: <b>{file.type || "unknown"}</b></span>
            <span>Duration: <b>{formatDuration(duration)}</b></span>
            <button type="button" className="button secondary" onClick={removeFile}><X size={14} /> Remove</button>
          </div>
        )}
        {validationError && <div className="notice error" role="alert">{validationError}</div>}

        {file && !validationError && (
          <>
            <h2>2. Configure session</h2>
            <div className="settings-grid two-up">
              <section>
                <label>
                  Session name
                  <input aria-label="Session name" value={name} onChange={(e) => setName(e.target.value)} required minLength={1} maxLength={160} />
                </label>
                <label>
                  Classroom
                  <select aria-label="Classroom" value={classroomId} onChange={(e) => setClassroomId(e.target.value)}>
                    <option value="">Unassigned</option>
                    {classrooms.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </label>
              </section>
              <section>
                <label>
                  Course
                  <select aria-label="Course" value={courseId} onChange={(e) => setCourseId(e.target.value)}>
                    <option value="">Unassigned</option>
                    {courses.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}
                  </select>
                </label>
                <label>
                  Activity context
                  <select aria-label="Activity context" value={activityContext} onChange={(e) => setActivityContext(e.target.value)}>
                    {ACTIVITY_CONTEXTS.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}
                  </select>
                </label>
              </section>
            </div>
            <label className="toggle consent" style={{ marginTop: 12 }}>
              <span>I confirm I have consent to record and analyze this video for anonymous classroom research. AmbiSense uses anonymous, session-local tracking and does not identify individuals.</span>
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} required aria-required="true" />
            </label>

            <h2>3. Upload</h2>
            <button disabled={busy || !consent || Boolean(job)}>
              <Film size={18} /> {busy ? `Uploading ${uploadProgress}%` : "Upload and queue analysis"}
            </button>
            {busy && (
              <div className="progress">
                <span>UPLOADING (file transfer, not analysis)</span>
                <b>{uploadProgress}%</b>
                <div role="progressbar" aria-valuenow={uploadProgress} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress">
                  <i style={{ width: `${uploadProgress}%` }} />
                </div>
              </div>
            )}
          </>
        )}
        {message && <div className="notice error" role="alert">{message}</div>}
      </form>

      {job && (
        <section className="table-card">
          <h2>4. Processing</h2>
          <p>
            <StatusBadge status={job.status} label={(job.stage || job.status).replace(/_/g, " ")} /> · Job <code>{job.job_id?.slice(0, 8)}</code> · Session #{job.session_id}
          </p>
          {!isTerminal && (
            <ol className="timeline" aria-label="Processing stages" style={{ display: "flex", gap: 8, flexWrap: "wrap", listStyle: "none", padding: 0 }}>
              {PROCESSING_STAGES.map((stage, index) => (
                <li key={stage} style={{ opacity: index <= stageIndex ? 1 : 0.4 }}>
                  {index < stageIndex ? <CheckCircle2 size={13} style={{ verticalAlign: "-2px" }} aria-hidden="true" /> : null} {stage.replace(/_/g, " ")}
                </li>
              ))}
            </ol>
          )}
          <div className="progress">
            <span aria-live="polite">{job.processed_frames ?? 0} / {job.total_frames ?? 0} frames · {job.processing_speed ?? 0} FPS{job.eta_seconds ? ` · ETA ${Math.round(job.eta_seconds)}s` : ""}</span>
            <b>{job.progress ?? 0}%</b>
            <div role="progressbar" aria-valuenow={job.progress ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label="Processing progress">
              <i style={{ width: `${job.progress ?? 0}%` }} />
            </div>
          </div>

          {job.status === "FAILED" && (
            <ErrorState
              title="Processing failed"
              message={job.error || "The video could not be processed."}
              code={job.failure_code}
              onRetry={() => void retry()}
            />
          )}
          {job.status === "FAILED" && (
            <p className="muted">Troubleshooting: confirm the file is a valid, non-corrupted recording and re-upload if the retry above does not succeed.</p>
          )}

          {job.status === "COMPLETED" && (
            <div className="actions">
              <Link className="button" to={`/sessions/${job.session_id}`}><CheckCircle2 size={15} /> Open session</Link>
              {job.report_ready && <a className="button secondary" href={`/api/sessions/${job.session_id}/report?format=pdf`}><Download size={15} /> View report</a>}
              {job.report_ready && <a className="button secondary" href={`/api/sessions/${job.session_id}/report?format=csv`}><Download size={15} /> Download CSV</a>}
              <button type="button" className="button secondary" onClick={startOver}><RotateCcw size={15} /> Upload another video</button>
            </div>
          )}
          {job.status !== "COMPLETED" && job.status !== "FAILED" && (
            <p className="muted"><AlertTriangle size={13} style={{ verticalAlign: "-2px" }} aria-hidden="true" /> Artifacts and report actions become available once processing completes.</p>
          )}
        </section>
      )}
    </>
  );
}
