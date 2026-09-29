/* eslint-disable react-hooks/set-state-in-effect -- notes load once for the session and reload after a save */
import { Pencil } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { apiProblem, formatDateTime, type ApiProblem } from "../constants";
import { api } from "../services/api";
import { EmptyState, ErrorState, LoadingSkeleton } from "./States";
import { useToast } from "./Toast";

type Note = { id: number; body: string; review_status: string; version: number; edited: boolean; created_at: string; updated_at: string; can_edit: boolean; author: { id: number | null; display_name: string; role: string | null } };
const STATUSES = ["OPEN", "REVIEWED", "RESOLVED"];

/** Persistent, session-scoped notes: author and role are recorded server-side; only the author or an administrator can edit. */
export function SessionNotes({ sessionId }: { sessionId: number | string }) {
  const { can } = useAuth();
  const { show } = useToast();
  const [notes, setNotes] = useState<Note[]>([]);
  const [state, setState] = useState<"loading" | "ok" | "error" | "forbidden">("loading");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<{ id: number; body: string; status: string } | null>(null);
  const canWrite = can("ADMINISTRATOR", "INSTRUCTOR", "REVIEWER");

  const load = useCallback(() => {
    let cancelled = false;
    setState((current) => (current === "ok" ? "ok" : "loading")); // a reload after saving keeps the list on screen instead of flashing a skeleton
    api.get("/v1/notes", { params: { scope_type: "SESSION", scope_id: sessionId } })
      .then((response) => { if (!cancelled) { setNotes(Array.isArray(response.data) ? response.data : []); setState("ok"); } })
      .catch((error) => { if (cancelled) return; const failure = apiProblem(error, "Notes could not be loaded."); setProblem(failure); setState(failure.status === 403 ? "forbidden" : "error"); });
    return () => { cancelled = true; };
  }, [sessionId]);
  useEffect(() => load(), [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setSaving(true);
    try { await api.post("/v1/notes", { scope_type: "SESSION", scope_id: Number(sessionId), body: draft.trim() }); setDraft(""); show("Note saved.", "success"); load(); }
    catch (error) { show(apiProblem(error, "The note could not be saved. Your text is kept.").message, "error"); }
    finally { setSaving(false); }
  }
  async function save(note: Note) {
    if (!editing || !editing.body.trim()) return;
    setSaving(true);
    try { await api.put(`/v1/notes/${note.id}`, { body: editing.body.trim(), review_status: editing.status, version: note.version }); setEditing(null); show("Note updated.", "success"); load(); }
    catch (error) {
      const failure = apiProblem(error, "The note could not be updated.");
      show(failure.status === 409 ? "This note was changed by someone else. Reload and try again." : failure.message, "error");
      if (failure.status === 409) { setEditing(null); load(); }
    } finally { setSaving(false); }
  }

  return (
    <div className="stack">
      {state === "loading" && <LoadingSkeleton kind="row" count={2} />}
      {state === "forbidden" && <EmptyState title="You are not authorized to view notes for this session" />}
      {state === "error" && <ErrorState message={problem?.message ?? "Notes could not be loaded."} code={problem?.requestId} onRetry={load} />}
      {state === "ok" && notes.length === 0 && <EmptyState title="No notes yet" description={canWrite ? "Add the first note for reviewers of this session." : "Notes added by reviewers will appear here."} />}
      {state === "ok" && notes.length > 0 && (
        <ul className="match-list" aria-label="Session notes">
          {notes.map((note) => (
            <li className="note-item" key={note.id}>
              <header>
                <span><b>{note.author.display_name}</b>{note.author.role ? ` · ${note.author.role.toLowerCase()}` : ""}</span>
                <span>{formatDateTime(note.created_at)}{note.edited ? ` · edited ${formatDateTime(note.updated_at)} (v${note.version})` : ""} · <span className="badge badge-neutral">{note.review_status.toLowerCase()}</span></span>
              </header>
              {editing?.id === note.id ? (
                <div className="stack">
                  <label className="field"><span>Edit note</span><textarea value={editing.body} onChange={(event) => setEditing({ ...editing, body: event.target.value })} maxLength={10000} /></label>
                  <label className="field" style={{ maxWidth: 220 }}><span>Review status</span><select value={editing.status} onChange={(event) => setEditing({ ...editing, status: event.target.value })}>{STATUSES.map((value) => <option key={value} value={value}>{value.toLowerCase()}</option>)}</select></label>
                  <div className="actions"><button className="button small" disabled={saving || !editing.body.trim()} onClick={() => void save(note)}>Save changes</button><button className="button secondary small" onClick={() => setEditing(null)}>Cancel</button></div>
                </div>
              ) : (
                <>
                  <p>{note.body}</p>
                  {note.can_edit && <button className="button ghost small" style={{ marginTop: 8 }} onClick={() => setEditing({ id: note.id, body: note.body, status: note.review_status })} aria-label={`Edit note by ${note.author.display_name}`}><Pencil size={13} /> Edit</button>}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {state !== "forbidden" && (canWrite ? (
        <form onSubmit={create} className="stack" aria-label="New note form">
          <label className="field"><span>Add a note</span><textarea value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={10000} placeholder="Observations for other reviewers (avoid naming individual students)" /></label>
          <div><button type="submit" className="button" disabled={saving || !draft.trim()}>Save note</button></div>
        </form>
      ) : <p className="muted">Your role can read notes but not add them.</p>)}
    </div>
  );
}
