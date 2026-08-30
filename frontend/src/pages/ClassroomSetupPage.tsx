/* eslint-disable react-hooks/exhaustive-deps */
import { Save, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import {
  movePolygon,
  normalizePoint,
  polygonValid,
  removeVertex,
  updateVertex,
  type Point,
} from "../utils/polygon";
type Region = {
  region_key: string;
  name: string;
  region_type: string;
  polygon: Point[];
  active: boolean;
};
const metrics = [
  "occupancy",
  "raised_hands",
  "participation",
  "camera_visibility",
  "model_confidence",
];
export function ClassroomSetupPage() {
  const [classrooms, setClassrooms] = useState<any[]>([]),
    [classroomId, setClassroomId] = useState(1),
    [layouts, setLayouts] = useState<any[]>([]),
    [sessions, setSessions] = useState<any[]>([]),
    [sessionId, setSessionId] = useState(""),
    [compareSessionId, setCompareSessionId] = useState(""),
    [points, setPoints] = useState<Point[]>([]),
    [regions, setRegions] = useState<Region[]>([]),
    [selected, setSelected] = useState(-1),
    [dragVertex, setDragVertex] = useState<number | null>(null),
    [moveStart, setMoveStart] = useState<Point | null>(null),
    [name, setName] = useState("Seat 01"),
    [type, setType] = useState("SEAT"),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [preview, setPreview] = useState<any>(null),
    [heatmap, setHeatmap] = useState<any>(null),
    [metric, setMetric] = useState("occupancy"),
    [regionFilter, setRegionFilter] = useState(""),
    [range, setRange] = useState({ start: "", end: "", interval: "5" });
  const referenceUrl = `/api/v1/classrooms/${classroomId}/reference-image?cache=${layouts[0]?.version || 0}`;
  function loadLayouts(id = classroomId) {
    api.get(`/v1/classrooms/${id}/layouts`).then((r) => {
      setLayouts(r.data);
      setRegions(r.data[0]?.regions || []);
      setSelected(-1);
    });
  }
  useEffect(() => {
    Promise.all([
      api.get("/v1/classrooms"),
      api.get("/v1/sessions", {
        params: { include_tests: true, page_size: 100 },
      }),
    ]).then(([a, b]) => {
      setClassrooms(a.data);
      setSessions(b.data.items);
      if (a.data[0]) setClassroomId(a.data[0].id);
    });
  }, []);
  useEffect(() => loadLayouts(), [classroomId]);
  function svgPoint(e: React.PointerEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    return normalizePoint(
      e.clientX - box.left,
      e.clientY - box.top,
      box.width,
      box.height,
    );
  }
  function canvasDown(e: React.PointerEvent<SVGSVGElement>) {
    if (selected >= 0) return;
    setPoints((old) => [...old, svgPoint(e)]);
  }
  function vertexDown(e: React.PointerEvent, index: number) {
    e.stopPropagation();
    setDragVertex(index);
    (e.currentTarget as SVGCircleElement).setPointerCapture(e.pointerId);
  }
  function vertexMove(e: React.PointerEvent<SVGCircleElement>) {
    if (dragVertex === null || selected < 0) return;
    const svg = e.currentTarget.ownerSVGElement!,
      box = svg.getBoundingClientRect(),
      next = normalizePoint(
        e.clientX - box.left,
        e.clientY - box.top,
        box.width,
        box.height,
      );
    setRegions((old) =>
      old.map((r, i) =>
        i === selected
          ? { ...r, polygon: updateVertex(r.polygon, dragVertex, next) }
          : r,
      ),
    );
  }
  function regionDown(e: React.PointerEvent, index: number) {
    e.stopPropagation();
    setSelected(index);
    const svg = e.currentTarget.ownerSVGElement!,
      box = svg.getBoundingClientRect();
    setMoveStart(
      normalizePoint(
        e.clientX - box.left,
        e.clientY - box.top,
        box.width,
        box.height,
      ),
    );
  }
  function regionMove(e: React.PointerEvent<SVGPolygonElement>, index: number) {
    if (moveStart === null || selected !== index || dragVertex !== null) return;
    const svg = e.currentTarget.ownerSVGElement!,
      box = svg.getBoundingClientRect(),
      now = normalizePoint(
        e.clientX - box.left,
        e.clientY - box.top,
        box.width,
        box.height,
      ),
      dx = now.x - moveStart.x,
      dy = now.y - moveStart.y;
    setRegions((old) =>
      old.map((r, i) =>
        i === index ? { ...r, polygon: movePolygon(r.polygon, dx, dy) } : r,
      ),
    );
    setMoveStart(now);
  }
  function add() {
    if (!polygonValid(points)) {
      setMessage("Polygon requires at least three non-collinear points.");
      return;
    }
    setRegions((old) => [
      ...old,
      {
        region_key: `region_${Date.now()}`,
        name,
        region_type: type,
        polygon: points,
        active: true,
      },
    ]);
    setPoints([]);
    setSelected(regions.length);
    setName(`Seat ${String(regions.length + 2).padStart(2, "0")}`);
  }
  async function save() {
    if (regions.some((r) => !polygonValid(r.polygon))) {
      setMessage("Fix invalid polygons before saving.");
      return;
    }
    setBusy(true);
    try {
      const response = await api.post(`/v1/classrooms/${classroomId}/layouts`, {
        name: `Layout ${layouts.length + 1}`,
        reference_image_path: layouts[0]?.reference_image_path || null,
        regions,
      });
      setLayouts((old) => [response.data, ...old]);
      setMessage(`Saved layout version ${response.data.version}.`);
    } catch (e: any) {
      setMessage(e.response?.data?.detail || "Layout save failed.");
    } finally {
      setBusy(false);
    }
  }
  async function uploadReference(file?: File) {
    if (!file) return;
    setBusy(true);
    const data = new FormData();
    data.append("file", file);
    try {
      await api.post(`/v1/classrooms/${classroomId}/reference-image`, data, {
        params: { layout_id: layouts[0]?.id },
      });
      setMessage("Reference image uploaded.");
      setLayouts((old) => [...old]);
    } catch (e: any) {
      setMessage(e.response?.data?.detail || "Reference upload failed.");
    } finally {
      setBusy(false);
    }
  }
  async function captureReference() {
    if (!sessionId) {
      setMessage("Select a retained video session before capturing a frame.");
      return;
    }
    setBusy(true);
    try {
      await api.post(
        `/v1/classrooms/${classroomId}/reference-image/capture`,
        null,
        {
          params: {
            session_id: sessionId,
            timestamp: range.start === "" ? 0 : Number(range.start),
            layout_id: layouts[0]?.id,
          },
        },
      );
      setMessage("Reference frame captured from the retained source video.");
      loadLayouts();
    } catch (e: any) {
      setMessage(e.response?.data?.detail || "Reference capture failed.");
    } finally {
      setBusy(false);
    }
  }
  async function refreshPreview() {
    if (!sessionId) return;
    try {
      setPreview(
        (await api.get(`/v1/sessions/${sessionId}/regions/preview`)).data,
      );
    } catch {
      setPreview({ status: "UNAVAILABLE", tracks: [] });
    }
  }
  useEffect(() => {
    if (!sessionId) {
      return;
    }
    const timer = window.setInterval(refreshPreview, 2000);
    return () => window.clearInterval(timer);
  }, [sessionId]);
  async function loadHeatmap() {
    if (!sessionId) return;
    setHeatmap(
      (
        await api.post(`/v1/sessions/${sessionId}/regions/heatmap`, {
          metric,
          start_seconds: range.start === "" ? null : Number(range.start),
          end_seconds: range.end === "" ? null : Number(range.end),
          aggregation_interval: Number(range.interval),
          region_ids: regionFilter ? [regionFilter] : [],
          compare_session_id:
            compareSessionId === "" ? null : Number(compareSessionId),
        })
      ).data,
    );
  }
  const heat = useMemo(
    () =>
      Object.fromEntries(
        (heatmap?.cells || []).map((c: any) => [
          c.region_id,
          c.status === "AVAILABLE"
            ? Math.min(
                1,
                Number(c.value || 0) / (metric === "occupancy" ? 10 : 100),
              )
            : 0,
        ]),
      ),
    [heatmap, metric],
  );
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Classroom Setup</h1>
          <p>Versioned normalized regions and privacy-safe matching preview</p>
        </div>
        <button onClick={save} disabled={!regions.length || busy}>
          <Save size={16} />
          {busy ? "Saving…" : "Save new version"}
        </button>
      </div>
      <div className="live-controls">
        <select
          value={classroomId}
          onChange={(e) => setClassroomId(Number(e.target.value))}
        >
          {classrooms.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} · capacity {c.capacity}
            </option>
          ))}
        </select>
        <label className="button secondary">
          <Upload size={15} />
          Reference image
          <input
            hidden
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(e) => uploadReference(e.target.files?.[0])}
          />
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Region name"
        />
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {[
            "SEAT",
            "ZONE",
            "INSTRUCTOR",
            "PROJECTOR",
            "ENTRANCE",
            "EXIT",
            "EXCLUDED",
          ].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <button onClick={add}>Add polygon</button>
        <button
          className="secondary"
          onClick={() => {
            setPoints([]);
            setSelected(-1);
          }}
        >
          Drawing mode
        </button>
      </div>
      {message && <div className="notice">{message}</div>}
      <div className="detail-layout">
        <section className="chart-card">
          <h2>Interactive layout editor</h2>
          <svg
            viewBox="0 0 1000 600"
            onPointerDown={canvasDown}
            onPointerUp={() => {
              setDragVertex(null);
              setMoveStart(null);
            }}
            style={{
              width: "100%",
              background: `#0b1220 url(${referenceUrl}) center/contain no-repeat`,
              cursor: selected < 0 ? "crosshair" : "default",
            }}
          >
            {regions.map((r, i) => (
              <g key={r.region_key}>
                <polygon
                  points={r.polygon
                    .map((p) => `${p.x * 1000},${p.y * 600}`)
                    .join(" ")}
                  fill={
                    r.region_type === "EXCLUDED"
                      ? "#ef444466"
                      : `rgba(49,216,160,${0.18 + (heat[r.region_key] || 0) * 0.65})`
                  }
                  stroke={
                    i === selected
                      ? "#fbbf24"
                      : r.region_type === "EXCLUDED"
                        ? "#ef4444"
                        : "#31d8a0"
                  }
                  strokeWidth={i === selected ? 5 : 2}
                  onPointerDown={(e) => regionDown(e, i)}
                  onPointerMove={(e) => regionMove(e, i)}
                />
                {i === selected &&
                  r.polygon.map((p, v) => (
                    <circle
                      key={v}
                      cx={p.x * 1000}
                      cy={p.y * 600}
                      r="9"
                      fill="#fbbf24"
                      onDoubleClick={() =>
                        setRegions((old) =>
                          old.map((region, index) =>
                            index === i
                              ? {
                                  ...region,
                                  polygon: removeVertex(region.polygon, v),
                                }
                              : region,
                          ),
                        )
                      }
                      onPointerDown={(e) => vertexDown(e, v)}
                      onPointerMove={vertexMove}
                    />
                  ))}
              </g>
            ))}
            {points.length > 0 && (
              <polyline
                points={points
                  .map((p) => `${p.x * 1000},${p.y * 600}`)
                  .join(" ")}
                fill="none"
                stroke="#60a5fa"
                strokeWidth="3"
              />
            )}
          </svg>
          <p className="muted">
            Drawing mode: click to add points. Select a region to drag it; drag
            gold vertices to edit; double-click a vertex to remove it. All
            coordinates remain between 0 and 1.
          </p>
        </section>
        <section className="table-card">
          <h2>Regions ({regions.length})</h2>
          {regions.map((r, i) => (
            <p key={r.region_key} onClick={() => setSelected(i)}>
              <b>{r.name}</b> · {r.region_type} · {r.polygon.length} points{" "}
              <button
                className="danger"
                onClick={(e) => {
                  e.stopPropagation();
                  setRegions((old) => old.filter((_, index) => index !== i));
                  setSelected(-1);
                }}
              >
                <Trash2 size={14} />
              </button>
            </p>
          ))}
        </section>
      </div>
      <section className="table-card">
        <h2>Preview and heat maps</h2>
        <div className="live-controls">
          <select
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
          >
            <option value="">Select a session</option>
            {sessions
              .filter((s) => s.classroom_id === classroomId || true)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {s.analytics_mode}
                </option>
              ))}
          </select>
          <select
            aria-label="Comparison session"
            value={compareSessionId}
            onChange={(e) => setCompareSessionId(e.target.value)}
          >
            <option value="">No comparison</option>
            {sessions
              .filter((session) => String(session.id) !== sessionId)
              .map((session) => (
                <option key={session.id} value={session.id}>
                  Compare with {session.name}
                </option>
              ))}
          </select>
          <button onClick={refreshPreview}>Refresh anonymous preview</button>
          <button className="secondary" onClick={captureReference} disabled={busy}>
            Capture reference at start time
          </button>
          <select value={metric} onChange={(e) => setMetric(e.target.value)}>
            {metrics.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
          <select
            aria-label="Region filter"
            value={regionFilter}
            onChange={(e) => setRegionFilter(e.target.value)}
          >
            <option value="">All regions</option>
            {regions.map((region) => (
              <option key={region.region_key} value={region.region_key}>
                {region.name}
              </option>
            ))}
          </select>
          <input
            type="number"
            placeholder="Start seconds"
            value={range.start}
            onChange={(e) => setRange({ ...range, start: e.target.value })}
          />
          <input
            type="number"
            placeholder="End seconds"
            value={range.end}
            onChange={(e) => setRange({ ...range, end: e.target.value })}
          />
          <input
            type="number"
            min="1"
            value={range.interval}
            onChange={(e) => setRange({ ...range, interval: e.target.value })}
          />
          <button onClick={loadHeatmap}>Load heat map</button>
        </div>
        {preview && (
          <div className="notice">
            Preview only · {preview.status} · {(preview.tracks || []).length}{" "}
            anonymous tracks · matched{" "}
            {
              (preview.tracks || []).filter(
                (t: any) => t.assignment === "MATCHED",
              ).length
            }{" "}
            · unmatched{" "}
            {
              (preview.tracks || []).filter(
                (t: any) => t.assignment === "UNMATCHED",
              ).length
            }{" "}
            · excluded{" "}
            {
              (preview.tracks || []).filter(
                (t: any) => t.assignment === "EXCLUDED",
              ).length
            }
          </div>
        )}
        {heatmap && (
          <div className="notice">
            {metric} heat map · {heatmap.status}. Unavailable evidence is
            transparent, never zero-filled.
          </div>
        )}
      </section>
    </>
  );
}
