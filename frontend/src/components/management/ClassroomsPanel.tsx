import { Map as MapIcon, Pencil, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ConfirmDialog, Dialog } from "../Dialog";
import { Pagination } from "../Pagination";
import { EmptyState, ErrorState, LoadingSkeleton } from "../States";
import { StatusBadge } from "../StatusBadge";
import { useToast } from "../Toast";
import { apiProblem } from "../../constants";
import { useRemoteList } from "../../hooks/useRemoteList";
import { api } from "../../services/api";

const PAGE_SIZE = 15;
type Room = { id: number; name: string; description: string | null; location_label: string | null; active: boolean; capacity: number; expected_students: number };
const EMPTY = { name: "", description: "", location_label: "", total_students: 40, total_seats: 40 };

export function ClassroomsPanel() {
  const { show } = useToast();
  const [q, setQ] = useState(""), [active, setActive] = useState(""), [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Room | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [archive, setArchive] = useState<Room | null>(null);
  const [busy, setBusy] = useState(false);
  const list = useRemoteList<Room>(async () => {
    const response = await api.get("/v1/classrooms", { params: { q: q || undefined, active: active === "" ? undefined : active === "true", page, page_size: PAGE_SIZE } });
    return { items: Array.isArray(response.data) ? response.data : [], total: null };
  }, { q, active, page });
  const hasNext = list.items.length === PAGE_SIZE;
  function open(room: Room | "new") {
    setEditing(room);
    setForm(room === "new" ? EMPTY : { name: room.name, description: room.description ?? "", location_label: room.location_label ?? "", total_students: room.expected_students, total_seats: room.capacity });
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim()) return;
    setBusy(true);
    const body = { name: form.name.trim(), description: form.description || null, location_label: form.location_label || null, total_students: form.total_students, total_seats: form.total_seats };
    try {
      if (editing === "new") await api.post("/v1/classrooms", body); else if (editing) await api.put(`/v1/classrooms/${editing.id}`, body);
      show(editing === "new" ? "Classroom created." : "Classroom updated.", "success"); setEditing(null); list.reload();
    } catch (error) { show(apiProblem(error, "The classroom could not be saved.").message, "error"); }
    finally { setBusy(false); }
  }
  async function toggleArchive() {
    const room = archive; setArchive(null);
    if (!room) return;
    try { await api.post(`/v1/classrooms/${room.id}/archive`, null, { params: { restore: !room.active } }); show(room.active ? "Classroom archived." : "Classroom restored.", "success"); list.reload(); }
    catch (error) { show(apiProblem(error, "The classroom could not be updated.").message, "error"); }
  }
  return (
    <section className="stack" aria-labelledby="classrooms-heading">
      <div className="filter-panel" style={{ margin: 0 }}>
        <h2 id="classrooms-heading">Classrooms</h2>
        <div className="filter-grid">
          <label className="field"><span>Search</span><input type="search" placeholder="Classroom name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></label>
          <label className="field"><span>Status</span><select value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }}><option value="">Any</option><option value="true">Active</option><option value="false">Archived</option></select></label>
          <div><button className="button" style={{ marginTop: 0 }} onClick={() => open("new")}><Plus size={14} /> Add classroom</button></div>
        </div>
      </div>
      {list.state === "loading" && <LoadingSkeleton kind="row" count={3} />}
      {list.state === "forbidden" && <EmptyState title="You are not authorized to manage classrooms" />}
      {list.state === "error" && <ErrorState message={list.problem?.message ?? "Classrooms could not be loaded."} code={list.problem?.requestId} onRetry={list.reload} />}
      {list.state === "ok" && list.items.length === 0 && <EmptyState title="No classrooms" description={q || active ? "Try clearing the filters." : "Add a classroom to calibrate seating regions and group sessions."} />}
      {list.state === "ok" && list.items.length > 0 && (
        <div className="table-card table-scroll">
          <table className="data-table">
            <caption className="sr-only">Classrooms</caption>
            <thead><tr><th scope="col">Classroom</th><th scope="col" className="num">Seat capacity</th><th scope="col" className="num">Expected students</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{list.items.map((room) => (
              <tr key={room.id}>
                <th scope="row" data-th="Classroom">{room.name}<small>{room.location_label || room.description || ""}</small></th>
                <td className="num" data-th="Seat capacity">{room.capacity}</td><td className="num" data-th="Expected students">{room.expected_students}</td>
                <td data-th="Status"><StatusBadge status={room.active ? "AVAILABLE" : "STOPPED"} label={room.active ? "Active" : "Archived"} /></td>
                <td data-th=""><div className="actions">
                  <button className="button secondary small" onClick={() => open(room)} aria-label={`Edit ${room.name}`}><Pencil size={13} /> Edit</button>
                  <Link className="button secondary small" to="/classroom-setup"><MapIcon size={13} /> Layout</Link>
                  <button className="button secondary small" onClick={() => setArchive(room)}>{room.active ? "Archive…" : "Restore…"}</button>
                </div></td>
              </tr>))}</tbody>
          </table>
          <Pagination page={page} pages={hasNext ? page + 1 : page} total={(page - 1) * PAGE_SIZE + list.items.length} noun="classrooms on this and earlier pages" onPage={setPage} />
        </div>
      )}
      <Dialog open={editing != null} title={editing === "new" ? "Add classroom" : "Edit classroom"} onClose={() => setEditing(null)}>
        <form onSubmit={submit} className="stack">
          <label className="field"><span>Name</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={120} required data-autofocus /></label>
          <label className="field"><span>Location label</span><input value={form.location_label} onChange={(e) => setForm({ ...form, location_label: e.target.value })} maxLength={160} /></label>
          <div className="filter-grid">
            <label className="field"><span>Seat capacity</span><input type="number" min={0} max={1000} value={form.total_seats} onChange={(e) => setForm({ ...form, total_seats: Number(e.target.value) })} /></label>
            <label className="field"><span>Expected students</span><input type="number" min={0} max={1000} value={form.total_students} onChange={(e) => setForm({ ...form, total_students: Number(e.target.value) })} /></label>
          </div>
          <label className="field"><span>Description</span><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} maxLength={2000} /></label>
          <div className="actions" style={{ justifyContent: "flex-end" }}><button type="button" className="button secondary" onClick={() => setEditing(null)}>Cancel</button><button type="submit" className="button" disabled={busy || !form.name.trim()}>{busy ? "Saving…" : "Save classroom"}</button></div>
        </form>
      </Dialog>
      <ConfirmDialog open={archive != null} title={archive?.active ? "Archive this classroom?" : "Restore this classroom?"} tone={archive?.active ? "danger" : "primary"} confirmLabel={archive?.active ? "Archive" : "Restore"} description={archive?.active ? `${archive.name} is hidden from new sessions. Existing sessions, layouts and reports are kept.` : `${archive?.name ?? "This classroom"} becomes available again.`} onCancel={() => setArchive(null)} onConfirm={() => void toggleArchive()} />
    </section>
  );
}
