import { KeyRound, Pencil, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ConfirmDialog, Dialog } from "../Dialog";
import { Pagination } from "../Pagination";
import { EmptyState, ErrorState, LoadingSkeleton } from "../States";
import { StatusBadge } from "../StatusBadge";
import { useToast } from "../Toast";
import { apiProblem, formatDateTime } from "../../constants";
import { useRemoteList } from "../../hooks/useRemoteList";
import { api } from "../../services/api";

const ROLES = ["ADMINISTRATOR", "INSTRUCTOR", "REVIEWER", "VIEWER"];
const PAGE_SIZE = 15;
const EMAIL = /^[^\s@]+@[^\s@]+$/;
type User = { id: number; email: string; display_name: string; role: string; active: boolean; created_at: string };

/** Administrator-only user management. Roles and deactivation are sensitive, so they need an explicit confirmation. */
export function UsersPanel({ selfId }: { selfId: number | null }) {
  const { show } = useToast();
  const [q, setQ] = useState(""), [role, setRole] = useState(""), [active, setActive] = useState(""), [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [confirm, setConfirm] = useState<{ user: User; display_name: string; role: string; active: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ email: "", display_name: "", role: "VIEWER", password: "" });
  const [draft, setDraft] = useState({ display_name: "", role: "VIEWER", active: true });
  const list = useRemoteList<User>(async () => {
    const response = await api.get("/v1/users", { params: { q: q || undefined, role: role || undefined, active: active === "" ? undefined : active === "true", page, page_size: PAGE_SIZE } });
    return { items: Array.isArray(response.data) ? response.data : [], total: Number(response.headers?.["x-total-count"] ?? NaN) || null };
  }, { q, role, active, page });
  const pages = Math.max(1, Math.ceil((list.total ?? list.items.length) / PAGE_SIZE));

  const formErrors: string[] = [];
  if (form.email && !EMAIL.test(form.email)) formErrors.push("Enter a valid email address.");
  if (form.password && form.password.length < 12) formErrors.push("The password must be at least 12 characters.");
  const canCreate = EMAIL.test(form.email) && form.display_name.trim().length > 0 && form.password.length >= 12;

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!canCreate) return;
    setBusy(true);
    try { await api.post("/v1/users", { ...form, email: form.email.trim(), display_name: form.display_name.trim() }); show(`User ${form.email} created.`, "success"); setCreating(false); setForm({ email: "", display_name: "", role: "VIEWER", password: "" }); list.reload(); }
    catch (error) { show(apiProblem(error, "The user could not be created.").message, "error"); }
    finally { setBusy(false); }
  }
  function requestSave() {
    if (!editing) return;
    const sensitive = draft.role !== editing.role || (editing.active && !draft.active);
    if (sensitive) setConfirm({ user: editing, ...draft }); else void save(editing, draft);
  }
  async function save(user: User, values: { display_name: string; role: string; active: boolean }) {
    setBusy(true); setConfirm(null);
    try { await api.put(`/v1/users/${user.id}`, values); show("User updated. Their existing sign-in sessions were revoked.", "success"); setEditing(null); list.reload(); }
    catch (error) { show(apiProblem(error, "The user could not be updated.").message, "error"); }
    finally { setBusy(false); }
  }

  return (
    <section className="stack" aria-labelledby="users-heading">
      <div className="filter-panel" style={{ margin: 0 }}>
        <h2 id="users-heading">Users</h2>
        <div className="filter-grid">
          <label className="field"><span>Search</span><input type="search" placeholder="Name or email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></label>
          <label className="field"><span>Role</span><select value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}><option value="">All roles</option>{ROLES.map((r) => <option key={r} value={r}>{r.toLowerCase()}</option>)}</select></label>
          <label className="field"><span>Status</span><select value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }}><option value="">Any</option><option value="true">Active</option><option value="false">Inactive</option></select></label>
          <div><button className="button" style={{ marginTop: 0 }} onClick={() => setCreating(true)}><Plus size={14} /> Add user</button></div>
        </div>
      </div>
      {list.state === "loading" && <LoadingSkeleton kind="row" count={4} />}
      {list.state === "forbidden" && <EmptyState title="Only administrators can manage users" description="Ask an administrator to change roles or accounts." />}
      {list.state === "error" && <ErrorState message={list.problem?.message ?? "Users could not be loaded."} code={list.problem?.requestId} onRetry={list.reload} />}
      {list.state === "ok" && list.items.length === 0 && <EmptyState title="No users match" description={q || role || active ? "Try clearing the filters." : "Create the first user account."} />}
      {list.state === "ok" && list.items.length > 0 && (
        <div className="table-card table-scroll">
          <table className="data-table">
            <caption className="sr-only">User accounts</caption>
            <thead><tr><th scope="col">Name</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Created</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {list.items.map((user) => (
                <tr key={user.id}>
                  <th scope="row" data-th="Name">{user.display_name}{user.id === selfId ? " (you)" : ""}<small>{user.email}</small></th>
                  <td data-th="Role">{user.role.toLowerCase()}</td>
                  <td data-th="Status"><StatusBadge status={user.active ? "AVAILABLE" : "STOPPED"} label={user.active ? "Active" : "Inactive"} /></td>
                  <td data-th="Created">{formatDateTime(user.created_at)}</td>
                  <td data-th=""><button className="button secondary small" onClick={() => { setEditing(user); setDraft({ display_name: user.display_name, role: user.role, active: user.active }); }} aria-label={`Edit ${user.display_name}`}><Pencil size={13} /> Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination page={page} pages={pages} total={list.total ?? list.items.length} noun="users" onPage={setPage} />
        </div>
      )}

      <Dialog open={creating} title="Add user" onClose={() => setCreating(false)}>
        <form onSubmit={create} className="stack">
          <label className="field"><span>Email</span><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} autoComplete="off" required data-autofocus /></label>
          <label className="field"><span>Display name</span><input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} maxLength={160} required /></label>
          <label className="field"><span>Role</span><select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{r.toLowerCase()}</option>)}</select></label>
          <div className="field"><label htmlFor="new-user-password"><KeyRound size={12} aria-hidden="true" /> Initial password</label><input id="new-user-password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" minLength={12} required aria-describedby="new-user-password-hint" /><p className="field-hint" id="new-user-password-hint">At least 12 characters. It is hashed on the server and never shown again.</p></div>
          {formErrors.map((message) => <p className="field-error" role="alert" key={message}>{message}</p>)}
          <div className="actions" style={{ justifyContent: "flex-end" }}><button type="button" className="button secondary" onClick={() => setCreating(false)}>Cancel</button><button type="submit" className="button" disabled={!canCreate || busy}>{busy ? "Creating…" : "Create user"}</button></div>
        </form>
      </Dialog>

      <Dialog open={editing != null} title={editing ? `Edit ${editing.display_name}` : "Edit user"} onClose={() => setEditing(null)}>
        {editing && (
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>{editing.email}</p>
            <label className="field"><span>Display name</span><input value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} maxLength={160} data-autofocus /></label>
            <div className="field"><label htmlFor="edit-user-role">Role</label><select id="edit-user-role" value={draft.role} disabled={editing.id === selfId} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{r.toLowerCase()}</option>)}</select>{editing.id === selfId && <p className="field-hint">You cannot change your own role.</p>}</div>
            <label className="chip" style={{ width: "fit-content" }}><input type="checkbox" checked={draft.active} disabled={editing.id === selfId} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} /> Account active</label>
            <div className="actions" style={{ justifyContent: "flex-end" }}><button className="button secondary" onClick={() => setEditing(null)}>Cancel</button><button className="button" disabled={busy || !draft.display_name.trim()} onClick={requestSave}>Save changes</button></div>
          </div>
        )}
      </Dialog>
      <ConfirmDialog open={confirm != null} title="Confirm access change" tone="danger" confirmLabel="Apply change" description={confirm ? `${confirm.user.display_name}: ${confirm.role !== confirm.user.role ? `role ${confirm.user.role.toLowerCase()} → ${confirm.role.toLowerCase()}` : ""}${confirm.role !== confirm.user.role && !confirm.active && confirm.user.active ? "; " : ""}${!confirm.active && confirm.user.active ? "account will be deactivated" : ""}. Their current sign-in sessions are revoked immediately.` : ""} busy={busy} onCancel={() => setConfirm(null)} onConfirm={() => confirm && void save(confirm.user, { display_name: confirm.display_name, role: confirm.role, active: confirm.active })} />
    </section>
  );
}
