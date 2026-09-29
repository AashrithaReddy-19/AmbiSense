/* eslint-disable react-hooks/set-state-in-effect -- settings, model health, retention policy and diagnostics load from the API */
import { AlertTriangle, Cpu, Lock, RotateCcw, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AudioStatus } from "../components/AudioStatus";
import { ConfirmDialog } from "../components/Dialog";
import { NOTICE_NOT_VALIDATED, NOTICE_NO_ACCURACY, PrivacyNotice } from "../components/PrivacyNotice";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { TabPanel, Tabs, type TabDefinition } from "../components/Tabs";
import { useToast } from "../components/Toast";
import { apiProblem, formatDateTime, type ApiProblem } from "../constants";
import { api } from "../services/api";

type Entry = { key: string; group: string; label: string; kind: "number" | "boolean" | "choice" | "text" | "readonly"; unit: string | null; min: number | null; max: number | null; choices: string[] | null; editable: boolean; restart_required: boolean; risky: boolean; description: string; value: any; source?: string };
type Draft = Record<string, string | boolean>;
const WARNINGS: Record<string, string> = {
  privacy_mode: "Turning privacy mode off is not recommended: it weakens the anonymous, session-local guarantees.",
  demo_mode: "Demo mode creates synthetic DEMO sessions. They are kept separate from real data but must never be presented as real evidence.",
};

export function toDraft(entries: Entry[]): Draft {
  return Object.fromEntries(entries.filter((e) => e.editable).map((e) => [e.key, e.kind === "boolean" ? Boolean(e.value) : String(e.value ?? "")]));
}
/** Range/choice validation with the same limits the server enforces (the server is still authoritative). */
export function validateEntry(entry: Entry, value: string | boolean | undefined): string | null {
  if (!entry.editable || entry.kind === "boolean") return null;
  const text = String(value ?? "").trim();
  if (entry.kind === "number") {
    if (text === "" || !Number.isFinite(Number(text))) return "Enter a number.";
    const number = Number(text);
    if (entry.min != null && number < entry.min) return `Must be at least ${entry.min}${entry.unit ? ` ${entry.unit}` : ""}.`;
    if (entry.max != null && number > entry.max) return `Must be at most ${entry.max}${entry.unit ? ` ${entry.unit}` : ""}.`;
    if (["expected_students", "total_seats", "process_every_n_frames", "retention_days", "transcript_retention_days"].includes(entry.key) && !Number.isInteger(number)) return "Must be a whole number.";
  } else if (entry.kind === "choice") {
    if (!entry.choices?.includes(text)) return `Choose one of: ${entry.choices?.join(", ")}.`;
  } else if (text === "") return "This value cannot be empty.";
  return null;
}
const coerce = (entry: Entry, value: string | boolean) => (entry.kind === "number" ? Number(value) : value);
const sameValue = (entry: Entry, draft: string | boolean) => (entry.kind === "boolean" ? Boolean(entry.value) === draft : String(entry.value ?? "") === String(draft));

function SettingRow({ entry, draft, error, onChange }: { entry: Entry; draft: string | boolean | undefined; error: string | null; onChange: (value: string | boolean) => void }) {
  const id = `setting-${entry.key}`;
  const hint = [entry.description, entry.unit && entry.kind === "number" ? `Unit: ${entry.unit}` : "", entry.min != null && entry.max != null ? `Range ${entry.min}–${entry.max}` : ""].filter(Boolean).join(" · ");
  return (
    <div className="region-row" style={{ gap: 4 }}>
      <div className="actions" style={{ justifyContent: "space-between" }}>
        <label htmlFor={id} style={{ fontWeight: 650 }}>{entry.label}</label>
        <span className="actions">
          {!entry.editable && <span className="badge badge-neutral"><Lock size={11} aria-hidden="true" /> Read-only · set by environment</span>}
          {entry.restart_required && <span className="badge badge-warning">Restart required</span>}
          {entry.editable && entry.risky && <span className="badge badge-warning"><AlertTriangle size={11} aria-hidden="true" /> Affects new results</span>}
        </span>
      </div>
      {!entry.editable ? (
        <output id={id} style={{ fontVariantNumeric: "tabular-nums" }}>{typeof entry.value === "boolean" ? (entry.value ? "Yes" : "No") : String(entry.value)}{entry.unit ? ` ${entry.unit}` : ""}</output>
      ) : entry.kind === "boolean" ? (
        <label className="chip" style={{ width: "fit-content" }}><input id={id} type="checkbox" checked={Boolean(draft)} onChange={(e) => onChange(e.target.checked)} aria-describedby={`${id}-hint`} /> {draft ? "On" : "Off"}</label>
      ) : entry.kind === "choice" ? (
        <select id={id} value={String(draft ?? "")} onChange={(e) => onChange(e.target.value)} aria-invalid={Boolean(error)} aria-describedby={`${id}-hint`}>{entry.choices?.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select>
      ) : (
        <input id={id} type={entry.kind === "number" ? "number" : "text"} inputMode={entry.kind === "number" ? "decimal" : undefined} step={entry.kind === "number" ? "any" : undefined} min={entry.min ?? undefined} max={entry.max ?? undefined} value={String(draft ?? "")} onChange={(e) => onChange(e.target.value)} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : `${id}-hint`} />
      )}
      {error && <p className="field-error" id={`${id}-error`} role="alert">{error}</p>}
      <p className="field-hint" id={`${id}-hint`}>{hint}</p>
      {entry.editable && draft !== undefined && WARNINGS[entry.key] && !sameValue(entry, draft) && (entry.key === "demo_mode" ? true : draft === false) && <p className="field-error" role="status">{WARNINGS[entry.key]}</p>}
    </div>
  );
}

export function SettingsPage() {
  const { show } = useToast();
  const [state, setState] = useState<"loading" | "ok" | "error" | "forbidden">("loading");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [catalog, setCatalog] = useState<{ groups: string[]; settings: Entry[]; audio: any; notice: string } | null>(null);
  const [serverValues, setServerValues] = useState<Record<string, any>>({});
  const [draft, setDraft] = useState<Draft>({});
  const [active, setActive] = useState("General");
  const [health, setHealth] = useState<any>(null);
  const [policy, setPolicy] = useState<any>(null);
  const [diagnostics, setDiagnostics] = useState<any>(null);
  const [stale, setStale] = useState<any>(null);
  const [staleSelected, setStaleSelected] = useState<number[]>([]);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [confirm, setConfirm] = useState<null | "settings" | "retention" | "recover">(null);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState("");
  const [reload, setReload] = useState(0);

  const load = useCallback(() => {
    let cancelled = false;
    setState("loading");
    Promise.all([api.get("/v1/settings/catalog"), api.get("/settings")]).then(([cat, values]) => {
      if (cancelled) return;
      setCatalog(cat.data); setServerValues(values.data); setDraft(toDraft(cat.data.settings)); setState("ok");
      // Secondary panels never block the page.
      api.get("/models/health").then((r) => !cancelled && setHealth(r.data)).catch(() => undefined);
      api.get("/v1/retention/policy").then((r) => !cancelled && setPolicy(r.data)).catch(() => undefined);
      api.get("/v1/system/diagnostics").then((r) => !cancelled && setDiagnostics(r.data)).catch(() => undefined);
      api.get("/v1/system/jobs/stale").then((r) => { if (cancelled) return; setStale(r.data); setStaleSelected(r.data.items.filter((item: any) => item.recoverable).map((item: any) => item.id)); }).catch(() => undefined);
      api.get("/v1/evaluation/status").then((r) => !cancelled && setEvaluation(r.data)).catch(() => undefined);
    }).catch((error) => { if (cancelled) return; const failure = apiProblem(error, "Settings could not be loaded."); setProblem(failure); setState(failure.status === 403 ? "forbidden" : "error"); });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => load(), [load, reload]);

  const entries = useMemo(() => catalog?.settings ?? [], [catalog]);
  const errors = useMemo(() => Object.fromEntries(entries.map((entry) => [entry.key, validateEntry(entry, draft[entry.key])])), [entries, draft]);
  const changed = entries.filter((entry) => entry.editable && draft[entry.key] !== undefined && !sameValue(entry, draft[entry.key]));
  const invalid = entries.some((entry) => errors[entry.key]);
  const risky = changed.filter((entry) => entry.risky);
  const tabs: TabDefinition[] = (catalog?.groups ?? []).map((group) => ({ id: group, label: group, badge: changed.filter((entry) => entry.group === group).length || null }));

  async function save() {
    setConfirm(null); setBusy(true); setServerError("");
    const payload = { ...serverValues, ...Object.fromEntries(changed.map((entry) => [entry.key, coerce(entry, draft[entry.key])])) };
    try {
      const response = await api.put("/settings", payload, { params: risky.length ? { confirm_risky: true } : undefined });
      show(`Saved ${changed.length} setting${changed.length === 1 ? "" : "s"}. They apply to new processing jobs; earlier results are unchanged.`, "success");
      setServerValues(response.data.settings); setReload((n) => n + 1);
    } catch (error) { const failure = apiProblem(error, "Settings could not be saved."); setServerError(failure.message); show(failure.message, "error"); }
    finally { setBusy(false); }
  }
  async function archiveOld() {
    setConfirm(null); setBusy(true);
    try { const response = await api.post("/v1/retention/sessions/run", null, { params: { confirm: true } }); show(`Archived ${response.data.archived} session(s). Nothing was deleted.`, "success"); setReload((n) => n + 1); }
    catch (error) { show(apiProblem(error, "Retention could not be applied.").message, "error"); }
    finally { setBusy(false); }
  }
  async function recover() {
    setConfirm(null); setBusy(true);
    try { const response = await api.post("/v1/system/jobs/recover", null, { params: { confirm: true, session_ids: staleSelected }, paramsSerializer: { indexes: null } }); show(`${response.data.count} interrupted job(s) were marked failed and can be retried. The change is recorded in the audit trail.`, "success"); setReload((n) => n + 1); }
    catch (error) { show(apiProblem(error, "Jobs could not be recovered.").message, "error"); }
    finally { setBusy(false); }
  }

  if (state === "loading") return <LoadingSkeleton kind="card" count={3} />;
  if (state === "forbidden") return <EmptyState title="Only administrators can view settings" description="Ask an administrator to review or change the configuration." />;
  if (state === "error" || !catalog) return <ErrorState message={problem?.message ?? "Settings could not be loaded."} code={problem?.requestId} onRetry={() => setReload((n) => n + 1)} />;
  const demo = Boolean(serverValues.demo_mode);
  const runner = diagnostics?.worker;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>{catalog.notice}</p>
        </div>
        <span className={`demo ${demo ? "" : "real"}`}>{demo ? "DEMO MODE" : "REAL ANALYTICS"}</span>
      </div>
      <PrivacyNotice variant="compact" showValidation />

      <Tabs tabs={tabs} active={active} onChange={setActive} label="Settings groups" idPrefix="settings" />
      {catalog.groups.map((group) => {
        const groupEntries = entries.filter((entry) => entry.group === group);
        return (
          <TabPanel id={group} active={active} idPrefix="settings" key={group}>
            <div className="stack">
              {group === "Models" && (
                <section className="model-health" aria-labelledby="model-health-heading">
                  <h2 id="model-health-heading"><Cpu size={19} aria-hidden="true" /> Model health{health ? ` · ${health.device} · ${health.mode}` : ""}</h2>
                  {!health ? <LoadingSkeleton kind="row" count={1} /> : (
                    <div>{health.models.map((model: any) => <article key={model.name}><StatusBadge status={model.loaded ? "AVAILABLE" : "INSUFFICIENT_EVIDENCE"} label={model.loaded ? "Loaded" : "Unavailable"} /><span><b>{model.name}</b><small>{model.path}</small></span></article>)}</div>
                  )}
                </section>
              )}
              {group === "Optional Audio" && <div className="table-card"><AudioStatus capabilities={catalog.audio} /></div>}
              {group === "Feature Flags" && demo && <div className="banner warning" role="status">Demo mode is on: new uploads produce synthetic DEMO data, kept separate from real analytics.</div>}
              {group === "Thresholds" && <div className="banner info" role="status">Thresholds decide what counts as possible prolonged eye closure, yawning or off-forward orientation. They are not validated on real classroom footage, so change them only with a documented reason. Changes affect new jobs only.</div>}
              <section className="table-card" aria-labelledby={`group-${group}`}>
                <h2 id={`group-${group}`}>{group}</h2>
                {groupEntries.length === 0 ? <p className="muted">No configurable options in this group.</p> : (
                  <div className="stack">{groupEntries.map((entry) => <SettingRow key={entry.key} entry={entry} draft={draft[entry.key]} error={errors[entry.key]} onChange={(value) => setDraft((old) => ({ ...old, [entry.key]: value }))} />)}</div>
                )}
              </section>

              {group === "Privacy & Retention" && (
                <section className="table-card" aria-labelledby="retention-heading">
                  <h2 id="retention-heading">Retention policy</h2>
                  {!policy ? <LoadingSkeleton kind="row" count={1} /> : (
                    <>
                      <p>Sessions older than <b>{policy.retention_days} days</b> can be <b>archived</b> (hidden, reversible). Sessions are deleted only by an explicit action on a single session, which also removes its files and is recorded in the audit trail.</p>
                      <p className="muted">Transcripts: {policy.transcripts.enabled ? (policy.test_sessions.scheduled_enabled ? `removed after ${policy.transcripts.days} days by the scheduled cleanup` : `policy is ${policy.transcripts.days} days, applied only when you run it (scheduled cleanup is off)`) : "retention disabled"} · Test sessions: {policy.test_sessions.scheduled_enabled && policy.test_sessions.cleanup_enabled ? `scheduled cleanup ${policy.test_sessions.action.toLowerCase()}s them after ${policy.test_sessions.age_hours} h` : "no automatic cleanup (starting the server never changes existing sessions)"}.</p>
                      <p><b>{policy.eligible_sessions.length}</b> session{policy.eligible_sessions.length === 1 ? " is" : "s are"} eligible (cutoff {formatDateTime(policy.cutoff)}).</p>
                      {policy.eligible_sessions.length > 0 && <ul style={{ maxHeight: 160, overflow: "auto" }}>{policy.eligible_sessions.slice(0, 20).map((s: any) => <li key={s.id}>#{s.id} · {s.name} · {formatDateTime(s.created_at)}</li>)}</ul>}
                      <button className="button danger" disabled={busy || policy.eligible_sessions.length === 0} onClick={() => setConfirm("retention")}>Archive {policy.eligible_sessions.length} session(s)…</button>
                    </>
                  )}
                </section>
              )}
              {group === "System" && (
                <section className="table-card" aria-labelledby="system-heading">
                  <h2 id="system-heading">Diagnostics</h2>
                  {!diagnostics ? <p className="muted">Diagnostics are unavailable (they can be disabled by the log level).</p> : (
                    <>
                      <ul>
                        <li>Database: {diagnostics.database.dialect}{diagnostics.database.alembic_revision ? ` · migration ${diagnostics.database.alembic_revision}` : ""}</li>
                        <li>Readiness: <b>{diagnostics.readiness.status.replace("_", " ")}</b> ({Object.entries(diagnostics.readiness.checks).map(([name, check]: any) => `${name} ${check.ok ? "ok" : "failing"}`).join(", ")})</li>
                        <li>Job runner: {runner.mode.replace("_", " ").toLowerCase()} · {runner.durable ? "durable" : "not durable (jobs end if the server restarts)"} · queue {runner.queue_depth} · stale {runner.stale_jobs}</li>
                      </ul>
                      {diagnostics.configuration.issues.length > 0 && <div className="banner warning" role="status"><div><b>Configuration notes</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{diagnostics.configuration.issues.map((issue: any) => <li key={`${issue.setting}-${issue.message}`}><b>{issue.setting}</b>: {issue.message}</li>)}</ul></div></div>}
                      {stale && stale.total > 0 && (
                        <section className="stale-panel" aria-labelledby="stale-heading">
                          <h3 id="stale-heading">Sessions that look stuck ({stale.total})</h3>
                          <p>{stale.explanation}</p>
                          <p className="muted">Nothing has been changed. Review the list, then choose which video jobs to mark as failed so they can be retried. Live captures cannot be resumed and are never changed here.</p>
                          <table>
                            <caption className="sr-only">Sessions that claim to be running but have no worker</caption>
                            <thead><tr><th scope="col"><span className="sr-only">Select</span></th><th scope="col">Session</th><th scope="col">Recorded state</th><th scope="col">Stuck for</th><th scope="col">What happens</th></tr></thead>
                            <tbody>
                              {stale.items.map((item: any) => (
                                <tr key={item.id}>
                                  <td data-th="">{item.recoverable ? <input type="checkbox" aria-label={`Select ${item.name} (#${item.id})`} checked={staleSelected.includes(item.id)} onChange={() => setStaleSelected((old) => (old.includes(item.id) ? old.filter((id) => id !== item.id) : [...old, item.id]))} /> : null}</td>
                                  <td data-th="Session">{item.name}<small>#{item.id} · {item.source_type}</small></td>
                                  <td data-th="Recorded state"><StatusBadge status={item.status} /><span className="badge badge-warning">Stale</span></td>
                                  <td data-th="Stuck for">{item.age_minutes >= 120 ? `${Math.round(item.age_minutes / 60)} h` : `${Math.round(item.age_minutes)} min`}</td>
                                  <td data-th="What happens">{item.recoverable ? "Can be marked failed, then retried" : "Left unchanged"}<small>{item.reason}</small></td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <p className="muted">{stale.not_running.STOPPED} stopped and {stale.not_running.CREATED} created live session(s) are not running jobs and are not treated as stale.</p>
                          <button className="button secondary" disabled={busy || staleSelected.length === 0} onClick={() => setConfirm("recover")}>Mark {staleSelected.length} selected job(s) as failed…</button>
                        </section>
                      )}
                    </>
                  )}
                  {evaluation && <div className="banner info" style={{ marginTop: 12 }} role="status"><div><b>{evaluation.headline || NOTICE_NOT_VALIDATED}</b> {evaluation.detail || NOTICE_NO_ACCURACY}</div></div>}
                </section>
              )}
            </div>
          </TabPanel>
        );
      })}

      <div className="filter-panel" style={{ position: "sticky", bottom: 12, marginTop: 16, marginBottom: 0, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }} role="region" aria-label="Save settings">
        <span aria-live="polite">{changed.length === 0 ? "No unsaved changes." : `${changed.length} unsaved change${changed.length === 1 ? "" : "s"}${risky.length ? ` (${risky.length} affect analytics or privacy)` : ""}.`}</span>
        {invalid && <span className="field-error" role="alert">Fix the highlighted values to save.</span>}
        {serverError && <span className="field-error" role="alert">{serverError}</span>}
        <span style={{ flex: 1 }} />
        <button className="button secondary" style={{ marginTop: 0 }} disabled={changed.length === 0 || busy} onClick={() => { setDraft(toDraft(entries)); setServerError(""); }}><RotateCcw size={14} /> Discard</button>
        <button className="button" style={{ marginTop: 0 }} disabled={changed.length === 0 || invalid || busy} onClick={() => (risky.length ? setConfirm("settings") : void save())}><Save size={15} /> {busy ? "Saving…" : "Save changes"}</button>
      </div>

      <ConfirmDialog open={confirm === "settings"} title="Apply analytics and privacy changes?" tone="danger" confirmLabel="Apply changes" description="These settings change how new sessions are analysed or how data is kept. Existing sessions are not reprocessed. The change is recorded in the audit trail." onCancel={() => setConfirm(null)} onConfirm={() => void save()}>
        <ul>{changed.map((entry) => <li key={entry.key}><b>{entry.label}</b>: {String(entry.value)} → {String(draft[entry.key])}{entry.unit && entry.kind === "number" ? ` ${entry.unit}` : ""}</li>)}</ul>
      </ConfirmDialog>
      <ConfirmDialog open={confirm === "retention"} title="Archive old sessions?" tone="danger" confirmLabel="Archive sessions" description={`${policy?.eligible_sessions.length ?? 0} session(s) older than ${policy?.retention_days} days will be hidden from normal lists. Their evidence and files are kept and they can be restored.`} onCancel={() => setConfirm(null)} onConfirm={() => void archiveOld()} />
      <ConfirmDialog open={confirm === "recover"} title="Mark interrupted jobs as failed?" tone="primary" confirmLabel="Mark as failed" description="The selected video jobs claim to be running but nothing is processing them. They will be marked failed so they can be retried. Each change is recorded in the audit trail. Live sessions are not touched." onCancel={() => setConfirm(null)} onConfirm={() => void recover()}>
        <ul>{(stale?.items ?? []).filter((item: any) => staleSelected.includes(item.id)).map((item: any) => <li key={item.id}>#{item.id} · {item.name} · recorded as {item.status.replace(/_/g, " ").toLowerCase()}</li>)}</ul>
      </ConfirmDialog>
    </>
  );
}
