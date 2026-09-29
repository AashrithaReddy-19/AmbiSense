/* eslint-disable react-hooks/set-state-in-effect -- the notification list synchronizes with its filters and reloads after each action */
import { AlertOctagon, AlertTriangle, CheckCheck, Info, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Pagination } from "../components/Pagination";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { useToast } from "../components/Toast";
import { apiProblem, formatDateTime, type ApiProblem } from "../constants";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api } from "../services/api";

export type NotificationItem = { id: number; category: string; severity: "CRITICAL" | "WARNING" | "INFO"; title: string; message: string; evidence: Record<string, unknown>; session_id: number | null; link: string | null; read: boolean; dismissed: boolean; created_at: string };
const CATEGORIES = ["POOR_CAMERA", "POOR_AUDIO", "MODEL_PROVIDER_UNAVAILABLE", "INSUFFICIENT_EVIDENCE", "PROCESSING_FAILED"];
const CATEGORY_LABEL: Record<string, string> = { POOR_CAMERA: "Poor camera quality", POOR_AUDIO: "Poor audio quality", MODEL_PROVIDER_UNAVAILABLE: "Model unavailable", INSUFFICIENT_EVIDENCE: "Insufficient evidence", PROCESSING_FAILED: "Processing failed" };
const SEVERITY = { CRITICAL: { icon: AlertOctagon, label: "Critical", tone: "danger" }, WARNING: { icon: AlertTriangle, label: "Warning", tone: "warning" }, INFO: { icon: Info, label: "Info", tone: "info" } } as const;
const DEFAULTS = { category: "", severity: "", status: "", dismissed: "no" };
const PAGE_SIZE = 15;

/** Advisory, per-session notifications - never one per frame. Read/dismiss state is stored on the server. */
export function NotificationsPage() {
  const { show } = useToast();
  const { applied, draft, update, apply, reset, activeCount, params, setExtra } = useUrlFilters(DEFAULTS);
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false; // ignore a slow older response after the filters changed again
    setState("loading");
    api.get("/v1/notifications", { params: { category: applied.category || undefined, severity: applied.severity || undefined, read: applied.status === "" ? undefined : applied.status === "read", include_dismissed: applied.dismissed === "yes", page, page_size: PAGE_SIZE } })
      .then((response) => { if (cancelled) return; setItems(Array.isArray(response.data) ? response.data : []); setTotal(Number(response.headers?.["x-total-count"] ?? response.data?.length ?? 0)); setUnread(Number(response.headers?.["x-unread-count"] ?? 0)); setState("ok"); })
      .catch((error) => { if (cancelled) return; setProblem(apiProblem(error, "Notifications could not be loaded.")); setState("error"); });
    return () => { cancelled = true; };
  }, [applied, page, tick]);

  const refresh = useCallback(() => setTick((n) => n + 1), []);
  async function act(item: NotificationItem, kind: "read" | "dismiss") {
    try { await api.post(`/v1/notifications/${item.id}/${kind}`); show(kind === "read" ? "Marked as read." : "Notification dismissed.", "success"); refresh(); }
    catch (error) { show(apiProblem(error, "That action could not be completed.").message, "error"); }
  }
  async function readAll() {
    setBusy(true);
    try { const response = await api.post("/v1/notifications/read-all", null, { params: { category: applied.category || undefined } }); show(response.data.updated ? `Marked ${response.data.updated} notification(s) as read.` : "Everything was already read.", "success"); refresh(); }
    catch (error) { show(apiProblem(error, "Notifications could not be updated.").message, "error"); }
    finally { setBusy(false); }
  }
  async function generate() {
    setBusy(true);
    try { const response = await api.post("/v1/notifications/generate"); show(response.data.created ? `${response.data.created} new advisory notification(s) created. Duplicates are skipped.` : "No new advisories: nothing new needs your attention.", "info"); refresh(); }
    catch (error) { show(apiProblem(error, "Sessions could not be checked.").message, "error"); }
    finally { setBusy(false); }
  }
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Notifications</h1>
          <p>Advisory signals about evidence quality and processing, one per session issue. They are prompts to review, not conclusions about anyone.</p>
        </div>
        <div className="actions">
          <button className="button secondary" onClick={() => void generate()} disabled={busy}><RefreshCw size={14} /> Check sessions</button>
          <button className="button" onClick={() => void readAll()} disabled={busy || unread === 0}><CheckCheck size={15} /> Mark all as read{applied.category ? " in category" : ""}</button>
        </div>
      </div>

      <form className="filter-panel" aria-label="Notification filters" onSubmit={(e) => { e.preventDefault(); apply({}, ["page"]); }}>
        <h2>Filters {activeCount > 0 && <span className="count-pill">{activeCount} active</span>} <span className="muted" aria-live="polite" style={{ fontWeight: 400 }}>{unread} unread</span></h2>
        <div className="filter-grid">
          <label className="field"><span>Category</span><select value={draft.category} onChange={(e) => update("category", e.target.value)}><option value="">All categories</option>{CATEGORIES.map((value) => <option key={value} value={value}>{CATEGORY_LABEL[value]}</option>)}</select></label>
          <label className="field"><span>Severity</span><select value={draft.severity} onChange={(e) => update("severity", e.target.value)}><option value="">All severities</option><option value="critical">Critical</option><option value="warning">Warning</option><option value="info">Info</option></select></label>
          <label className="field"><span>Status</span><select value={draft.status} onChange={(e) => update("status", e.target.value)}><option value="">Read and unread</option><option value="unread">Unread only</option><option value="read">Read only</option></select></label>
          <label className="field"><span>Dismissed</span><select value={draft.dismissed} onChange={(e) => update("dismissed", e.target.value)}><option value="no">Hide dismissed</option><option value="yes">Include dismissed</option></select></label>
        </div>
        <div className="filter-actions"><button type="submit" className="button">Apply filters</button><button type="button" className="button secondary" onClick={() => reset(["page"])} disabled={activeCount === 0}>Reset</button></div>
      </form>

      {state === "loading" && <LoadingSkeleton kind="row" count={4} />}
      {state === "error" && <ErrorState message={problem?.message ?? "Notifications could not be loaded."} code={problem?.requestId} onRetry={refresh} />}
      {state === "ok" && items.length === 0 && <EmptyState title="No notifications" description={activeCount > 0 ? "Nothing matches these filters." : "You're all caught up. Use “Check sessions” to look for new advisories."} />}
      {state === "ok" && items.length > 0 && (
        <>
          <ul className="match-list" aria-label="Notifications">
            {items.map((item) => {
              const severity = SEVERITY[item.severity] ?? SEVERITY.INFO, Icon = severity.icon;
              return (
                <li key={item.id} className={`match-card severity-${item.severity.toLowerCase()}`} style={{ opacity: item.dismissed ? 0.6 : 1 }}>
                  <h3><span className={`badge badge-${severity.tone}`}><Icon size={12} aria-hidden="true" />{severity.label}</span> {item.title} {!item.read && <span className="badge badge-info">Unread</span>}{item.dismissed && <span className="badge badge-neutral">Dismissed</span>}</h3>
                  <div>{item.message}</div>
                  <div className="muted">{CATEGORY_LABEL[item.category] ?? item.category} · {formatDateTime(item.created_at)}</div>
                  {Object.keys(item.evidence ?? {}).length > 0 && <details><summary>Evidence</summary><pre>{JSON.stringify(item.evidence, null, 2)}</pre></details>}
                  <div className="actions">
                    {item.link ? <Link className="button secondary small" to={item.link}>Open session</Link> : item.session_id ? <span className="muted">The linked session no longer exists.</span> : null}
                    {!item.read && <button className="button secondary small" onClick={() => void act(item, "read")}>Mark read</button>}
                    {!item.dismissed && <button className="button ghost small" onClick={() => void act(item, "dismiss")}>Dismiss</button>}
                  </div>
                </li>
              );
            })}
          </ul>
          <Pagination page={page} pages={pages} total={total} noun="notifications" onPage={(next) => setExtra("page", next === 1 ? null : String(next))} />
        </>
      )}
    </>
  );
}
