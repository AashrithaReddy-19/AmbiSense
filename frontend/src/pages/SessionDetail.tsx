import { Download, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EventReviewRow } from "../components/EventReviewRow";
import { SessionIntelligence } from "../components/SessionIntelligence";
import { api } from "../services/api";
import type { Session } from "../types";
const activities = [
  "LECTURE",
  "EXAMINATION",
  "GROUP_DISCUSSION",
  "LABORATORY",
  "STUDENT_PRESENTATION",
  "INDEPENDENT_WRITING",
  "READING",
  "VIDEO_SCREENING",
  "BREAK",
];
export function SessionDetail() {
  const { id } = useParams(),
    navigate = useNavigate();
  const [session, setSession] = useState<Session | null>(null),
    [summary, setSummary] = useState<any>(null),
    [timeline, setTimeline] = useState<any[]>([]),
    [events, setEvents] = useState<any[]>([]),
    [quality, setQuality] = useState<any>(null),
    [regions, setRegions] = useState<any>(null),
    [activity, setActivity] = useState("LECTURE");
  const load = useCallback(() => {
    Promise.all([
      api.get(`/sessions/${id}`),
      api.get(`/sessions/${id}/analytics`),
      api.get(`/sessions/${id}/timeline`),
      api.get(`/sessions/${id}/events`),
      api.get(`/v1/sessions/${id}/quality`),
      api.get(`/v1/sessions/${id}/regions`),
    ]).then(([a, b, c, d, e, f]) => {
      setSession(a.data);
      setSummary(b.data);
      setTimeline(c.data);
      setEvents(d.data);
      setQuality(e.data);
      setRegions(f.data);
      setActivity(a.data.activity_context);
    });
  }, [id]);
  useEffect(load, [load]);
  async function remove() {
    if (!confirm("Delete this session and its stored videos/reports?")) return;
    await api.delete(`/sessions/${id}`);
    navigate("/sessions");
  }
  async function changeActivity(value: string) {
    setActivity(value);
    await api.post(`/v1/sessions/${id}/activities`, {
      activity_type: value,
      start_seconds: timeline.at(-1)?.timestamp || 0,
      confirmed: true,
    });
    load();
  }
  if (!session || !summary)
    return <div className="state">Loading session evidence…</div>;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{session.name}</h1>
          <p>
            Session #{id} · {session.analytics_mode} · {session.status}
          </p>
        </div>
        <div className="actions">
          <a className="button" href={`/api/sessions/${id}/report?format=pdf`}>
            <Download size={16} />
            PDF
          </a>
          <a
            className="button secondary"
            href={`/api/sessions/${id}/report?format=csv`}
          >
            <Download size={16} />
            CSV
          </a>
          <button className="button danger" onClick={remove}>
            <Trash2 size={16} />
            Delete
          </button>
        </div>
      </div>
      <div className="notice">
        AmbiSense estimates observable classroom signals. It does not make
        medical, psychological or pedagogical diagnoses.
      </div>
      <div className="live-controls">
        <label>
          Activity context{" "}
          <select
            value={activity}
            onChange={(e) => changeActivity(e.target.value)}
          >
            {activities.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <span>
          Quality: <b>{quality?.status || "UNAVAILABLE"}</b>
        </span>
        <span>
          Regions: <b>{regions?.status || "UNCALIBRATED"}</b>
        </span>
      </div>
      {quality?.warnings?.map((w: string) => (
        <div className="notice" key={w}>
          {w}
        </div>
      ))}
      <div className="detail-layout">
        <section className="video-panel">
          <video controls src={`/api/sessions/${id}/video?annotated=true`} />
          {!session.annotated_video_path && (
            <div className="video-empty">
              Annotated video becomes available after real processing completes.
            </div>
          )}
        </section>
        <div className="summary-grid">
          {[
            ["Occupancy rate", summary.average_occupancy_rate],
            ["Verified attendance", "Unavailable"],
            ["Observable participation", summary.average_engagement],
            ["Visual orientation", summary.average_attention],
            ["Possible fatigue", summary.average_fatigue],
            ["Peak occupancy", summary.peak_students],
          ].map(([key, value]) => (
            <article key={String(key)}>
              <small>{key}</small>
              <b>
                {String(value ?? "—")}
                {typeof value === "number" ? "%" : ""}
              </b>
            </article>
          ))}
        </div>
      </div>
      <section className="chart-card">
        <h2>Observable timeline</h2>
        {timeline.length ? (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={timeline}>
              <CartesianGrid stroke="#25304a" vertical={false} />
              <XAxis dataKey="timestamp" />
              <YAxis domain={[0, 100]} />
              <Tooltip />
              <Legend />
              <Area
                dataKey="engagement"
                name="Observable participation"
                stroke="#31d8a0"
                fill="#31d8a022"
              />
              <Area
                dataKey="attention"
                name="Visual orientation"
                stroke="#60a5fa"
                fill="transparent"
              />
              <Area
                dataKey="fatigue"
                name="Possible fatigue"
                stroke="#fb7185"
                fill="transparent"
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="empty">No timeline observations.</div>
        )}
      </section>
      <section className="table-card">
        <h2>Region analytics</h2>
        {regions?.regions?.length ? (
          regions.regions.map((r: any) => (
            <p key={r.region_id}>
              <b>{r.name}</b> · unique tracks {r.estimated_unique_tracks} ·
              visual coverage {r.visual_coverage ?? "Unavailable"}%
            </p>
          ))
        ) : (
          <div className="empty">
            {regions?.label || "No calibrated region evidence."}
          </div>
        )}
        <h2>Event review</h2>
        {events.length ? (
          events.map((event: any) => (
            <EventReviewRow key={event.id} event={event} onSaved={load} />
          ))
        ) : (
          <div className="empty">No events detected.</div>
        )}
      </section>
      <SessionIntelligence sessionId={id!} />
    </>
  );
}
