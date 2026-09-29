/* eslint-disable react-hooks/set-state-in-effect -- the permission matrix loads once */
import { Check, Minus } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorState, LoadingSkeleton } from "../States";
import { apiProblem, type ApiProblem } from "../../constants";
import { api } from "../../services/api";

/** Feature access is derived from the server's permission lists (never hard-coded per role in the UI). */
export const FEATURES: Array<{ label: string; permission: string; description: string }> = [
  { label: "View sessions and analytics", permission: "session:view", description: "Open sessions, trends, comparisons and search results they are allowed to see." },
  { label: "Upload videos and start live sessions", permission: "session:upload", description: "Create sessions and archive or delete their own sessions." },
  { label: "Manage classrooms and layouts", permission: "classroom:manage", description: "Create classrooms and draw seating regions." },
  { label: "Manage courses and members", permission: "course:manage", description: "Create courses, add members and assign sessions." },
  { label: "Review events and transcripts", permission: "event:review", description: "Confirm, exclude or correct observations." },
  { label: "Write collaboration notes", permission: "note:write", description: "Add and edit notes on sessions they can access." },
  { label: "Generate and download reports", permission: "report:generate", description: "Produce PDF and CSV reports." },
  { label: "Export aggregate data", permission: "export", description: "Download aggregate exports." },
  { label: "Manage users and settings", permission: "user:manage", description: "Create accounts, change roles, edit settings and run retention." },
];

type Permissions = { you: { role: string; permissions: string[] }; roles: Array<{ role: string; summary: string; permissions: string[] }>; auth_enabled: boolean };
const allows = (permissions: string[], permission: string) => permissions.includes("*") || permissions.includes(permission);

export function AccessPanel() {
  const [data, setData] = useState<Permissions | null>(null);
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setProblem(null);
    api.get("/v1/auth/permissions").then((r) => { if (!cancelled) setData(r.data); }).catch((e) => { if (!cancelled) setProblem(apiProblem(e, "Permissions could not be loaded.")); });
    return () => { cancelled = true; };
  }, [reload]);
  if (problem) return <ErrorState message={problem.message} code={problem.requestId} onRetry={() => setReload((n) => n + 1)} />;
  if (!data) return <LoadingSkeleton kind="row" count={4} />;
  return (
    <section className="stack" aria-labelledby="access-heading">
      <div className="table-card">
        <h2 id="access-heading">Your access</h2>
        <p>You are signed in as <b>{data.you.role.toLowerCase()}</b>. {data.roles.find((r) => r.role === data.you.role)?.summary}</p>
        {!data.auth_enabled && <p className="muted">Authentication is disabled, so this local instance treats every request as an administrator.</p>}
      </div>
      <div className="table-card table-scroll">
        <table className="data-table">
          <caption>Feature access by role</caption>
          <thead><tr><th scope="col">Feature</th>{data.roles.map((r) => <th scope="col" key={r.role} className="num">{r.role.toLowerCase()}{r.role === data.you.role ? " (you)" : ""}</th>)}</tr></thead>
          <tbody>{FEATURES.map((feature) => (
            <tr key={feature.permission}>
              <th scope="row" data-th="Feature">{feature.label}<small>{feature.description}</small></th>
              {data.roles.map((r) => { const yes = allows(r.permissions, feature.permission); return <td className="num" key={r.role} data-th={r.role.toLowerCase()}>{yes ? <><Check size={15} aria-hidden="true" /><span className="sr-only">Allowed</span></> : <><Minus size={15} aria-hidden="true" /><span className="sr-only">Not allowed</span></>}</td>; })}
            </tr>))}</tbody>
        </table>
        <p className="muted">Access to individual sessions also depends on the classroom owner and course membership. Permissions are enforced by the server; hiding a control here is only a convenience.</p>
      </div>
    </section>
  );
}
