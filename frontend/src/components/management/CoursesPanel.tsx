/* eslint-disable react-hooks/set-state-in-effect -- course members and sessions load when their drawer is opened */
import { Pencil, Plus, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ConfirmDialog, Dialog } from "../Dialog";
import { Pagination } from "../Pagination";
import { EmptyState, ErrorState, LoadingSkeleton } from "../States";
import { StatusBadge } from "../StatusBadge";
import { useToast } from "../Toast";
import { apiProblem, contextLabel } from "../../constants";
import { useRemoteList } from "../../hooks/useRemoteList";
import { api } from "../../services/api";

const PAGE_SIZE = 15;
const MEMBER_ROLES = ["INSTRUCTOR", "REVIEWER", "VIEWER"];
type Course = { id: number; code: string; name: string; description: string | null; academic_term: string | null; classroom_id: number | null; active: boolean };
const EMPTY = { code: "", name: "", description: "", academic_term: "", classroom_id: "", active: true };

function CourseMembers({ course, canListUsers }: { course: Course; canListUsers: boolean }) {
  const { show } = useToast();
  const [members, setMembers] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [userId, setUserId] = useState(""), [role, setRole] = useState("VIEWER");
  const [removing, setRemoving] = useState<any | null>(null);
  const load = useCallback(() => {
    setState("loading");
    api.get(`/v1/courses/${course.id}/members`).then((r) => { setMembers(r.data ?? []); setState("ok"); }).catch(() => setState("error"));
  }, [course.id]);
  useEffect(() => load(), [load]);
  useEffect(() => { if (canListUsers) api.get("/v1/users", { params: { page_size: 200 } }).then((r) => setUsers(Array.isArray(r.data) ? r.data : [])).catch(() => setUsers([])); }, [canListUsers]);
  async function add(event: FormEvent) {
    event.preventDefault();
    if (!userId) return;
    try { await api.post(`/v1/courses/${course.id}/members`, { user_id: Number(userId), membership_role: role }); show("Member saved.", "success"); setUserId(""); load(); }
    catch (error) { show(apiProblem(error, "The member could not be saved.").message, "error"); }
  }
  async function remove() {
    const target = removing; setRemoving(null);
    if (!target) return;
    try { await api.delete(`/v1/courses/${course.id}/members/${target.user_id}`); show("Member removed.", "success"); load(); }
    catch (error) { show(apiProblem(error, "The member could not be removed.").message, "error"); }
  }
  return (
    <div className="stack">
      {state === "loading" && <LoadingSkeleton kind="row" count={2} />}
      {state === "error" && <ErrorState message="Members could not be loaded." onRetry={load} />}
      {state === "ok" && members.length === 0 && <p className="muted">No members yet. Course members can see this course's sessions according to their role.</p>}
      {state === "ok" && members.length > 0 && (
        <ul className="match-list" aria-label="Course members">
          {members.map((member) => <li className="note-item" key={member.user_id}><header><span><b>{member.display_name}</b> · {member.email}</span><span>{member.membership_role.toLowerCase()}{member.active ? "" : " · inactive"}</span></header><button className="button ghost small" onClick={() => setRemoving(member)} aria-label={`Remove ${member.display_name}`}><Trash2 size={13} /> Remove</button></li>)}
        </ul>
      )}
      <form onSubmit={add} className="filter-grid" aria-label="Add a member">
        {canListUsers ? (
          <label className="field"><span>User</span><select value={userId} onChange={(e) => setUserId(e.target.value)}><option value="">Select a user</option>{users.filter((u) => u.active).map((u) => <option key={u.id} value={u.id}>{u.display_name} · {u.email}</option>)}</select></label>
        ) : (
          <div className="field"><label htmlFor="member-user-id">User ID</label><input id="member-user-id" type="number" min={1} value={userId} onChange={(e) => setUserId(e.target.value)} aria-describedby="member-user-id-hint" /><p className="field-hint" id="member-user-id-hint">Only administrators can browse users; enter the ID an administrator gave you.</p></div>
        )}
        <label className="field"><span>Membership role</span><select value={role} onChange={(e) => setRole(e.target.value)}>{MEMBER_ROLES.map((r) => <option key={r} value={r}>{r.toLowerCase()}</option>)}</select></label>
        <div><button type="submit" className="button" style={{ marginTop: 0 }} disabled={!userId}>Add / update member</button></div>
      </form>
      <ConfirmDialog open={removing != null} title="Remove this member?" description={removing ? `${removing.display_name} will lose access to this course's sessions unless they have access another way.` : ""} confirmLabel="Remove member" onCancel={() => setRemoving(null)} onConfirm={() => void remove()} />
    </div>
  );
}

function CourseSessions({ course }: { course: Course }) {
  const { show } = useToast();
  const [assigned, setAssigned] = useState<any[]>([]);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [sessionId, setSessionId] = useState("");
  const load = useCallback(() => {
    setState("loading");
    Promise.all([api.get(`/v1/courses/${course.id}/sessions`), api.get("/v1/sessions", { params: { page_size: 100 } }).catch(() => ({ data: { items: [] } }))])
      .then(([mine, all]) => { setAssigned(mine.data ?? []); setCandidates((all.data?.items ?? []).filter((s: any) => !s.course_id)); setState("ok"); }).catch(() => setState("error"));
  }, [course.id]);
  useEffect(() => load(), [load]);
  async function assign() {
    try { await api.post(`/v1/courses/${course.id}/sessions`, { session_id: Number(sessionId) }); show("Session assigned to the course.", "success"); setSessionId(""); load(); }
    catch (error) { show(apiProblem(error, "The session could not be assigned.").message, "error"); }
  }
  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>A session belongs to at most one course. Access to a session follows the course's members and its classroom.</p>
      {state === "loading" && <LoadingSkeleton kind="row" count={2} />}
      {state === "error" && <ErrorState message="Sessions could not be loaded." onRetry={load} />}
      {state === "ok" && assigned.length === 0 && <p className="muted">No sessions are assigned to this course yet.</p>}
      {state === "ok" && assigned.length > 0 && <ul className="match-list" aria-label="Course sessions">{assigned.map((s) => <li className="note-item" key={s.id}><header><span><Link to={`/sessions/${s.id}`}>{s.name}</Link></span><span><StatusBadge status={s.status} /> · {contextLabel(s.context)}</span></header></li>)}</ul>}
      <div className="filter-grid">
        <label className="field"><span>Assign an unassigned session</span><select value={sessionId} onChange={(e) => setSessionId(e.target.value)}><option value="">Select a session</option>{candidates.map((s) => <option key={s.id} value={s.id}>{s.name} (#{s.id})</option>)}</select></label>
        <div><button className="button" style={{ marginTop: 0 }} disabled={!sessionId} onClick={() => void assign()}>Assign to course</button></div>
      </div>
    </div>
  );
}

export function CoursesPanel({ canListUsers }: { canListUsers: boolean }) {
  const { show } = useToast();
  const [q, setQ] = useState(""), [active, setActive] = useState(""), [page, setPage] = useState(1);
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [editing, setEditing] = useState<Course | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [drawer, setDrawer] = useState<{ kind: "members" | "sessions"; course: Course } | null>(null);
  const [busy, setBusy] = useState(false);
  const list = useRemoteList<Course>(async () => {
    const response = await api.get("/v1/courses", { params: { q: q || undefined, active: active === "" ? undefined : active === "true", page, page_size: PAGE_SIZE } });
    return { items: Array.isArray(response.data) ? response.data : [], total: null };
  }, { q, active, page });
  useEffect(() => { api.get("/v1/classrooms").then((r) => setClassrooms(Array.isArray(r.data) ? r.data : [])).catch(() => setClassrooms([])); }, []);
  const classroomName = (id: number | null) => (id ? classrooms.find((room) => room.id === id)?.name ?? `#${id}` : "—");
  const hasNext = list.items.length === PAGE_SIZE;

  function open(course: Course | "new") {
    setEditing(course);
    setForm(course === "new" ? EMPTY : { code: course.code, name: course.name, description: course.description ?? "", academic_term: course.academic_term ?? "", classroom_id: course.classroom_id ? String(course.classroom_id) : "", active: course.active });
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.code.trim() || !form.name.trim()) return;
    setBusy(true);
    const body = { code: form.code.trim(), name: form.name.trim(), description: form.description || null, academic_term: form.academic_term || null, classroom_id: form.classroom_id ? Number(form.classroom_id) : null };
    try {
      if (editing === "new") await api.post("/v1/courses", body); else if (editing) await api.put(`/v1/courses/${editing.id}`, { ...body, active: form.active });
      show(editing === "new" ? "Course created." : "Course updated.", "success"); setEditing(null); list.reload();
    } catch (error) { show(apiProblem(error, "The course could not be saved.").message, "error"); }
    finally { setBusy(false); }
  }

  return (
    <section className="stack" aria-labelledby="courses-heading">
      <div className="filter-panel" style={{ margin: 0 }}>
        <h2 id="courses-heading">Courses</h2>
        <div className="filter-grid">
          <label className="field"><span>Search</span><input type="search" placeholder="Code or name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></label>
          <label className="field"><span>Status</span><select value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }}><option value="">Any</option><option value="true">Active</option><option value="false">Inactive</option></select></label>
          <div><button className="button" style={{ marginTop: 0 }} onClick={() => open("new")}><Plus size={14} /> Add course</button></div>
        </div>
      </div>
      {list.state === "loading" && <LoadingSkeleton kind="row" count={3} />}
      {list.state === "forbidden" && <EmptyState title="You are not authorized to manage courses" />}
      {list.state === "error" && <ErrorState message={list.problem?.message ?? "Courses could not be loaded."} code={list.problem?.requestId} onRetry={list.reload} />}
      {list.state === "ok" && list.items.length === 0 && <EmptyState title="No courses" description={q || active ? "Try clearing the filters." : "Add a course to group sessions and share them with reviewers."} />}
      {list.state === "ok" && list.items.length > 0 && (
        <div className="table-card table-scroll">
          <table className="data-table">
            <caption className="sr-only">Courses</caption>
            <thead><tr><th scope="col">Course</th><th scope="col">Term</th><th scope="col">Classroom</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{list.items.map((course) => (
              <tr key={course.id}>
                <th scope="row" data-th="Course">{course.code}<small>{course.name}</small></th>
                <td data-th="Term">{course.academic_term || "—"}</td><td data-th="Classroom">{classroomName(course.classroom_id)}</td>
                <td data-th="Status"><StatusBadge status={course.active ? "AVAILABLE" : "STOPPED"} label={course.active ? "Active" : "Inactive"} /></td>
                <td data-th=""><div className="actions">
                  <button className="button secondary small" onClick={() => open(course)} aria-label={`Edit ${course.code}`}><Pencil size={13} /> Edit</button>
                  <button className="button secondary small" onClick={() => setDrawer({ kind: "members", course })} aria-label={`Members of ${course.code}`}><Users size={13} /> Members</button>
                  <button className="button secondary small" onClick={() => setDrawer({ kind: "sessions", course })} aria-label={`Sessions of ${course.code}`}>Sessions</button>
                </div></td>
              </tr>))}</tbody>
          </table>
          <Pagination page={page} pages={hasNext ? page + 1 : page} total={(page - 1) * PAGE_SIZE + list.items.length} noun="courses on this and earlier pages" onPage={setPage} />
        </div>
      )}
      <Dialog open={editing != null} title={editing === "new" ? "Add course" : "Edit course"} onClose={() => setEditing(null)}>
        <form onSubmit={submit} className="stack">
          <label className="field"><span>Code</span><input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} maxLength={60} required data-autofocus /></label>
          <label className="field"><span>Name</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={180} required /></label>
          <label className="field"><span>Academic term</span><input value={form.academic_term} onChange={(e) => setForm({ ...form, academic_term: e.target.value })} maxLength={100} /></label>
          <label className="field"><span>Classroom</span><select value={form.classroom_id} onChange={(e) => setForm({ ...form, classroom_id: e.target.value })}><option value="">No classroom</option>{classrooms.map((room) => <option key={room.id} value={room.id}>{room.name}</option>)}</select></label>
          <label className="field"><span>Description</span><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} maxLength={2000} /></label>
          {editing !== "new" && <label className="chip" style={{ width: "fit-content" }}><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Course active</label>}
          <div className="actions" style={{ justifyContent: "flex-end" }}><button type="button" className="button secondary" onClick={() => setEditing(null)}>Cancel</button><button type="submit" className="button" disabled={busy || !form.code.trim() || !form.name.trim()}>{busy ? "Saving…" : "Save course"}</button></div>
        </form>
      </Dialog>
      <Dialog open={drawer != null} variant="drawer" title={drawer ? `${drawer.kind === "members" ? "Members" : "Sessions"} · ${drawer.course.code}` : ""} onClose={() => setDrawer(null)}>
        {drawer?.kind === "members" && <CourseMembers course={drawer.course} canListUsers={canListUsers} />}
        {drawer?.kind === "sessions" && <CourseSessions course={drawer.course} />}
      </Dialog>
    </section>
  );
}
