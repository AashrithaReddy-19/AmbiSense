import { Archive } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import type { Session } from "../types";
export function SessionsPage() {
  const [rows, setRows] = useState<Session[]>([]),
    [selected, setSelected] = useState<number[]>([]),
    [q, setQ] = useState(""),
    [status, setStatus] = useState(""),
    [mode, setMode] = useState(""),
    [archived, setArchived] = useState(false),
    [page, setPage] = useState(1),
    [pages, setPages] = useState(1),
    [feedback, setFeedback] = useState("");
  function load() {
    api
      .get("/v1/sessions", {
        params: {
          q: q || undefined,
          status: status || undefined,
          mode: mode || undefined,
          archived,
          page,
          page_size: 20,
        },
      })
      .then((r) => {
        setRows(r.data.items);
        setPages(r.data.pages);
        setSelected([]);
      });
  }
  useEffect(load, [q, status, mode, archived, page]);
  function toggle(id: number) {
    setSelected((old) =>
      old.includes(id) ? old.filter((value) => value !== id) : [...old, id],
    );
  }
  async function archiveOne(id: number) {
    await api.post(`/v1/sessions/${id}/archive`, null, {
      params: { archived: !archived },
    });
    load();
  }
  async function bulk() {
    if (
      !selected.length ||
      !confirm(
        `Archive ${selected.length} selected sessions? Active sessions will be skipped.`,
      )
    )
      return;
    try {
      const r = await api.post("/v1/sessions/bulk-archive", {
        session_ids: selected,
      });
      setFeedback(
        `Archived ${r.data.archived.length}; skipped ${r.data.skipped.length}; not found ${r.data.not_found.length}.`,
      );
      load();
    } catch (e: any) {
      setFeedback(e.response?.data?.detail || "Bulk archive failed.");
    }
  }
  const all = rows.length > 0 && rows.every((row) => selected.includes(row.id));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Sessions</h1>
          <p>Searchable anonymous classroom history</p>
        </div>
        <div className="actions">
          <button
            className="secondary"
            disabled={!selected.length}
            onClick={bulk}
          >
            <Archive size={15} />
            Archive selected ({selected.length})
          </button>
          <Link className="button" to="/upload">
            Upload video
          </Link>
        </div>
      </div>
      <div className="live-controls">
        <input
          placeholder="Search sessions"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {[
            "CREATED",
            "QUEUED",
            "PROCESSING",
            "COMPLETED",
            "FAILED",
            "STOPPED",
          ].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="">Real and demo</option>
          <option>REAL</option>
          <option>DEMO</option>
        </select>
        <label className="toggle">
          <span>Archived</span>
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => setArchived(e.target.checked)}
          />
        </label>
      </div>
      {feedback && <div className="notice">{feedback}</div>}
      <section className="table-card">
        {rows.length ? (
          <table>
            <thead>
              <tr>
                <th>
                  <input
                    aria-label="Select filtered page"
                    type="checkbox"
                    checked={all}
                    onChange={() =>
                      setSelected(
                        all
                          ? []
                          : rows
                              .filter(
                                (r) =>
                                  ![
                                    "PROCESSING",
                                    "INITIALIZING",
                                    "FINALIZING",
                                  ].includes(r.status),
                              )
                              .map((r) => r.id),
                      )
                    }
                  />
                </th>
                <th>Session</th>
                <th>Status</th>
                <th>Activity</th>
                <th>Progress</th>
                <th>Source</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${row.name}`}
                      checked={selected.includes(row.id)}
                      onChange={() => toggle(row.id)}
                    />
                  </td>
                  <td>
                    <Link to={`/sessions/${row.id}`}>{row.name}</Link>
                    <small>
                      #{row.id} · <b>{row.analytics_mode}</b>
                      {row.is_test ? " · API/TEST" : ""}
                    </small>
                  </td>
                  <td>
                    <span className={`status ${row.status.toLowerCase()}`}>
                      {row.status}
                    </span>
                    <small>{row.processing_stage}</small>
                  </td>
                  <td>{row.activity_context.replace(/_/g, " ")}</td>
                  <td>
                    {row.progress}%
                    <small>
                      {row.processed_frames}/{row.total_frames}
                    </small>
                  </td>
                  <td>
                    {row.source_type}
                    <small>{row.duration.toFixed(1)}s</small>
                  </td>
                  <td>
                    <button
                      className="secondary"
                      onClick={() => archiveOne(row.id)}
                    >
                      <Archive size={14} />
                      {archived ? "Restore" : "Archive"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty">No matching sessions.</div>
        )}
      </section>
      <div className="actions">
        <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          Previous
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
          Next
        </button>
      </div>
    </>
  );
}
