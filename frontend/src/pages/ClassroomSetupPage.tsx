/* eslint-disable react-hooks/set-state-in-effect -- classroom, layout and reference image load from the API whenever the selected classroom changes */
import { Hand, Maximize2, MousePointer2, PenTool, Plus, Redo2, Save, Trash2, Undo2, Upload, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { LayoutCanvas, MAX_ZOOM, MIN_ZOOM, REGION_STYLE, clampView, zoomView, type EditorRegion, type Tool, type View } from "../components/classroom/LayoutCanvas";
import { ConfirmDialog } from "../components/Dialog";
import { PrivacyNotice } from "../components/PrivacyNotice";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { apiProblem, formatDateTime, type ApiProblem } from "../constants";
import { useUndoRedo } from "../hooks/useUndoRedo";
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";
import { api } from "../services/api";
import { validateRegions, polygonProblem, PROBLEM_MESSAGE } from "../utils/layoutValidation";
import { movePolygon, removeVertex, updateVertex, clamp, type Point } from "../utils/polygon";

const HEAT_METRICS = ["occupancy", "raised_hands", "participation", "camera_visibility", "model_confidence"];
const INITIAL_VIEW: View = { zoom: 1, x: 0, y: 0 };
const toEditor = (regions: any[] = []): EditorRegion[] => regions.map((r) => ({ region_key: r.region_key, name: r.name, region_type: r.region_type, polygon: r.polygon.map((p: Point) => ({ x: p.x, y: p.y })), active: r.active !== false }));
let keyCounter = 0;
const newKey = () => `region_${Date.now().toString(36)}_${++keyCounter}`;
type Pending = { kind: "classroom"; id: number } | { kind: "layout"; layout: any } | { kind: "delete-region"; index: number } | { kind: "deactivate"; layout: any } | null;

export function ClassroomSetupPage() {
  const { can } = useAuth();
  const { show } = useToast();
  const canEdit = can("ADMINISTRATOR", "INSTRUCTOR");
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [classroomId, setClassroomId] = useState<number | null>(null);
  const [layouts, setLayouts] = useState<any[]>([]);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [reload, setReload] = useState(0);
  const editor = useUndoRedo<EditorRegion[]>([]);
  const regions = editor.value;
  const { undo: undoEdit, redo: redoEdit } = editor;
  const [savedKey, setSavedKey] = useState("[]");
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const [tool, setTool] = useState<Tool>("edit");
  const [selected, setSelected] = useState(-1);
  const [selectedVertex, setSelectedVertex] = useState<number | null>(null);
  const [draft, setDraft] = useState<Point[]>([]);
  const [drawMessage, setDrawMessage] = useState("");
  const [view, setView] = useState<View>(INITIAL_VIEW);
  const [name, setName] = useState("Seat 01");
  const [type, setType] = useState("SEAT");
  const [layoutName, setLayoutName] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageVersion, setImageVersion] = useState(0);
  const [serverIssues, setServerIssues] = useState<Array<{ message: string }>>([]);
  const [meta, setMeta] = useState({ name: "", description: "", location_label: "", total_students: 40, total_seats: 40 });
  const [sessions, setSessions] = useState<any[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [compareSessionId, setCompareSessionId] = useState("");
  const [captureAt, setCaptureAt] = useState("0");
  const [preview, setPreview] = useState<any>(null);
  const [heatmap, setHeatmap] = useState<any>(null);
  const [metric, setMetric] = useState("occupancy");
  const [regionFilter, setRegionFilter] = useState("");
  const [range, setRange] = useState({ start: "", end: "", interval: "5" });

  const dirty = JSON.stringify(regions) !== savedKey;
  const guard = useUnsavedChangesGuard(dirty);
  const validation = useMemo(() => validateRegions(regions), [regions]);
  const invalidKeys = useMemo(() => new Set(validation.errors.map((issue) => issue.region_key ?? "")), [validation]);
  const classroom = classrooms.find((c) => c.id === classroomId);

  // --- data loading -------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.get("/v1/classrooms"), api.get("/v1/sessions", { params: { include_tests: true, page_size: 100 } }).catch(() => ({ data: { items: [] } }))])
      .then(([rooms, sessionList]) => {
        if (cancelled) return;
        const list = Array.isArray(rooms.data) ? rooms.data : [];
        setClassrooms(list); setSessions(sessionList.data?.items ?? []);
        setClassroomId((current) => (current && list.some((room: any) => room.id === current) ? current : list[0]?.id ?? null));
        setState("ok");
      })
      .catch((error) => { if (!cancelled) { setProblem(apiProblem(error, "Classrooms could not be loaded.")); setState("error"); } });
    return () => { cancelled = true; };
  }, [reload]);

  const adoptLayout = useCallback((layout: any | undefined) => {
    const next = toEditor(layout?.regions);
    editor.reset(next); setSavedKey(JSON.stringify(next)); setLoadedVersion(layout?.version ?? null);
    setSelected(-1); setSelectedVertex(null); setDraft([]); setServerIssues([]); setView(INITIAL_VIEW);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (classroomId == null) return;
    let cancelled = false;
    api.get(`/v1/classrooms/${classroomId}/layouts`).then((response) => {
      if (cancelled) return;
      const list: any[] = response.data ?? [];
      setLayouts(list); adoptLayout(list.find((layout) => layout.active) ?? list[0]);
    }).catch((error) => { if (!cancelled) show(apiProblem(error, "Layouts could not be loaded.").message, "error"); });
    return () => { cancelled = true; };
  }, [classroomId, adoptLayout, show]); // deliberately not tied to `reload`: refreshing classroom details must never discard unsaved layout edits

  useEffect(() => {
    if (classroom) setMeta({ name: classroom.name ?? "", description: classroom.description ?? "", location_label: classroom.location_label ?? "", total_students: classroom.expected_students ?? 40, total_seats: classroom.capacity ?? 40 });
  }, [classroom]);

  // The reference image is fetched through axios so the bearer token is sent (an <image href> cannot carry it).
  useEffect(() => {
    if (classroomId == null) { setImageUrl(null); return; }
    let cancelled = false, created: string | null = null;
    api.get(`/v1/classrooms/${classroomId}/reference-image`, { responseType: "blob" })
      .then((response) => { if (cancelled) return; created = URL.createObjectURL(response.data as Blob); setImageUrl(created); })
      .catch(() => { if (!cancelled) setImageUrl(null); });
    return () => { cancelled = true; if (created) URL.revokeObjectURL(created); };
  }, [classroomId, imageVersion]);

  // Anonymous preview polling only while a session is chosen; cleared on change and unmount.
  const refreshPreview = useCallback(async () => {
    if (!sessionId) return;
    try { setPreview((await api.get(`/v1/sessions/${sessionId}/regions/preview`)).data); } catch { setPreview({ status: "UNAVAILABLE", tracks: [] }); }
  }, [sessionId]);
  useEffect(() => {
    if (!sessionId) return;
    const timer = window.setInterval(() => void refreshPreview(), 2000);
    return () => window.clearInterval(timer);
  }, [sessionId, refreshPreview]);

  // --- editing helpers ----------------------------------------------------------------
  const setView2 = (next: View) => setView(clampView(next));
  function guarded(action: Pending) { if (dirty) setPending(action); else void perform(action); }
  async function perform(action: Pending) {
    setPending(null);
    if (!action) return;
    if (action.kind === "classroom") setClassroomId(action.id);
    else if (action.kind === "layout") adoptLayout(action.layout);
    else if (action.kind === "delete-region") { editor.set((old) => old.filter((_, index) => index !== action.index)); setSelected(-1); setSelectedVertex(null); show("Region removed from the draft. Save a new version to keep the change.", "info"); }
    else if (action.kind === "deactivate") {
      try { await api.delete(`/v1/classrooms/${classroomId}/layouts/${action.layout.id}`); show(`Version ${action.layout.version} deactivated.`, "success"); setLayouts((old) => old.map((layout) => (layout.id === action.layout.id ? { ...layout, active: false } : layout))); }
      catch (error) { show(apiProblem(error, "The layout could not be deactivated.").message, "error"); }
    }
  }
  function finishPolygon() {
    const problem = polygonProblem(draft);
    if (problem) { setDrawMessage(PROBLEM_MESSAGE[problem]); return; }
    const region: EditorRegion = { region_key: newKey(), name: name.trim() || `Region ${regions.length + 1}`, region_type: type, polygon: draft, active: true };
    editor.set((old) => [...old, region]);
    setDraft([]); setDrawMessage(""); setSelected(regions.length); setTool("edit");
    setName(`Seat ${String(regions.length + 2).padStart(2, "0")}`);
  }
  const updateRegion = (index: number, patch: Partial<EditorRegion>) => editor.set((old) => old.map((region, i) => (i === index ? { ...region, ...patch } : region)));
  const moveVertexTo = (index: number, vertex: number, point: Point, record = true) => editor.set((old) => old.map((region, i) => (i === index ? { ...region, polygon: updateVertex(region.polygon, vertex, point) } : region)), record);
  const removePoint = (index: number, vertex: number) => {
    const region = regions[index];
    const next = removeVertex(region.polygon, vertex);
    if (next === region.polygon) { show("A polygon must keep at least three points that enclose an area.", "warning"); return; }
    updateRegion(index, { polygon: next }); setSelectedVertex(null);
  };

  function onCanvasKey(event: KeyboardEvent) {
    const step = event.shiftKey ? 0.02 : 0.005;
    if (tool === "draw") {
      if (event.key === "Enter") { event.preventDefault(); finishPolygon(); }
      else if (event.key === "Escape") { setDraft([]); setDrawMessage(""); }
      else if (event.key === "Backspace") { event.preventDefault(); setDraft((old) => old.slice(0, -1)); }
      return;
    }
    if (event.key === "+" || event.key === "=") { event.preventDefault(); setView2(zoomView(view, view.zoom * 1.25)); return; }
    if (event.key === "-") { event.preventDefault(); setView2(zoomView(view, view.zoom / 1.25)); return; }
    if (event.key === "0") { event.preventDefault(); setView(INITIAL_VIEW); return; }
    const arrows: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    const delta = arrows[event.key];
    if (tool === "edit" && selected >= 0 && delta) {
      event.preventDefault();
      if (selectedVertex != null) { const point = regions[selected].polygon[selectedVertex]; moveVertexTo(selected, selectedVertex, { x: clamp(point.x + delta[0]), y: clamp(point.y + delta[1]) }); }
      else editor.set((old) => old.map((region, i) => (i === selected ? { ...region, polygon: movePolygon(region.polygon, delta[0], delta[1]) } : region)));
    } else if (tool === "edit" && selected >= 0 && (event.key === "Delete" || event.key === "Backspace")) {
      event.preventDefault();
      if (selectedVertex != null) removePoint(selected, selectedVertex); else setPending({ kind: "delete-region", index: selected });
    } else if (delta) {
      event.preventDefault();
      setView2({ ...view, x: view.x + delta[0] * 1000, y: view.y + delta[1] * 600 });
    }
  }

  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); if (event.shiftKey) redoEdit(); else undoEdit(); }
      else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") { event.preventDefault(); redoEdit(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undoEdit, redoEdit]);

  // --- server actions -------------------------------------------------------------------
  async function save() {
    if (validation.errors.length) return;
    setBusy(true); setServerIssues([]);
    try {
      const response = await api.post(`/v1/classrooms/${classroomId}/layouts`, { name: layoutName.trim() || `Layout ${layouts.length + 1}`, reference_image_path: layouts[0]?.reference_image_path || null, regions });
      const saved = response.data;
      setLayouts((old) => [saved, ...old.map((layout) => ({ ...layout, active: false }))]);
      setSavedKey(JSON.stringify(regions)); setLoadedVersion(saved.version); setLayoutName(""); // what the user sees is what was saved
      show(`Saved layout version ${saved.version}.${saved.warnings?.length ? ` ${saved.warnings.length} overlap warning(s).` : ""}`, "success");
    } catch (error) {
      const failure = apiProblem(error, "The layout could not be saved.");
      setServerIssues(Array.isArray(failure.details) ? (failure.details as Array<{ message: string }>) : [{ message: failure.message }]);
      show(failure.message, "error");
    } finally { setBusy(false); }
  }
  async function saveMetadata() {
    if (!classroomId) return;
    setBusy(true);
    try { await api.put(`/v1/classrooms/${classroomId}`, meta); show("Classroom details saved.", "success"); setReload((n) => n + 1); }
    catch (error) { show(apiProblem(error, "Classroom details could not be saved.").message, "error"); }
    finally { setBusy(false); }
  }
  async function createClassroom() {
    setBusy(true);
    try { const response = await api.post("/v1/classrooms", { name: `New classroom ${classrooms.length + 1}`, total_students: 40, total_seats: 40 }); show("Classroom created. Rename it below.", "success"); setClassroomId(response.data.id); setReload((n) => n + 1); }
    catch (error) { show(apiProblem(error, "The classroom could not be created.").message, "error"); }
    finally { setBusy(false); }
  }
  async function uploadReference(file?: File) {
    if (!file || !classroomId) return;
    setBusy(true);
    const data = new FormData(); data.append("file", file);
    try { await api.post(`/v1/classrooms/${classroomId}/reference-image`, data, { params: { layout_id: layouts[0]?.id } }); show("Reference image uploaded.", "success"); setImageVersion((n) => n + 1); }
    catch (error) { show(apiProblem(error, "The reference image could not be uploaded.").message, "error"); }
    finally { setBusy(false); }
  }
  async function captureReference() {
    if (!sessionId) { show("Select a retained video session before capturing a frame.", "warning"); return; }
    setBusy(true);
    try { await api.post(`/v1/classrooms/${classroomId}/reference-image/capture`, null, { params: { session_id: sessionId, timestamp: Number(captureAt) || 0, layout_id: layouts[0]?.id } }); show("Reference frame captured from the retained source video.", "success"); setImageVersion((n) => n + 1); }
    catch (error) { show(apiProblem(error, "The reference frame could not be captured.").message, "error"); }
    finally { setBusy(false); }
  }
  async function loadHeatmap() {
    if (!sessionId) return;
    try { setHeatmap((await api.post(`/v1/sessions/${sessionId}/regions/heatmap`, { metric, start_seconds: range.start === "" ? null : Number(range.start), end_seconds: range.end === "" ? null : Number(range.end), aggregation_interval: Number(range.interval), region_ids: regionFilter ? [regionFilter] : [], compare_session_id: compareSessionId === "" ? null : Number(compareSessionId) })).data); }
    catch (error) { show(apiProblem(error, "The heat map could not be loaded.").message, "error"); }
  }
  const heat = useMemo(() => Object.fromEntries((heatmap?.cells || []).map((c: any) => [c.region_id, c.status === "AVAILABLE" ? Math.min(1, Number(c.value || 0) / (metric === "occupancy" ? 10 : 100)) : 0])), [heatmap, metric]);

  // --- render -------------------------------------------------------------------------------
  if (state === "loading") return <LoadingSkeleton kind="card" count={3} />;
  if (state === "error") return <ErrorState message={problem?.message ?? "Classrooms could not be loaded."} code={problem?.requestId} onRetry={() => { setState("loading"); setReload((n) => n + 1); }} />;
  if (classrooms.length === 0) return <EmptyState title="No classrooms yet" description={canEdit ? "Create a classroom to calibrate its seating regions." : "An administrator or instructor must create a classroom first."} action={canEdit ? <button className="button" onClick={() => void createClassroom()}><Plus size={14} /> Create classroom</button> : undefined} />;
  const region = selected >= 0 ? regions[selected] : null;
  const usedTypes = Array.from(new Set(regions.map((r) => r.region_type)));
  const summary = tool === "draw" ? `Drawing: ${draft.length} point${draft.length === 1 ? "" : "s"} placed.` : selected >= 0 ? `Selected region ${regions[selected]?.name}.` : "No region selected.";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Classroom Setup</h1>
          <p>Versioned, normalized seating regions and a privacy-safe matching preview. Nothing is inferred: only regions you draw are saved.</p>
        </div>
        <div className="actions">
          <button className="button secondary" onClick={editor.undo} disabled={!editor.canUndo} aria-label="Undo"><Undo2 size={15} /> Undo</button>
          <button className="button secondary" onClick={editor.redo} disabled={!editor.canRedo} aria-label="Redo"><Redo2 size={15} /> Redo</button>
          {canEdit && <button className="button" onClick={() => void save()} disabled={busy || validation.errors.length > 0 || !dirty || regions.length === 0}><Save size={16} /> {busy ? "Saving…" : "Save new version"}</button>}
        </div>
      </div>
      <PrivacyNotice variant="compact" />
      {dirty && <div className="banner warning" role="status"><b>Unsaved changes.</b> Save a new version to keep them; leaving this page discards them.</div>}
      {!canEdit && <div className="banner info" role="status">Your role can view layouts but not change them.</div>}

      <section className="filter-panel" aria-labelledby="classroom-heading">
        <h2 id="classroom-heading">Classroom</h2>
        <div className="filter-grid">
          <label className="field"><span>Classroom</span>
            <select value={classroomId ?? ""} onChange={(event) => guarded({ kind: "classroom", id: Number(event.target.value) })}>
              {classrooms.map((c) => <option key={c.id} value={c.id}>{c.name} · capacity {c.capacity}</option>)}
            </select></label>
          {canEdit && <div><button className="button secondary" style={{ marginTop: 0 }} onClick={() => void createClassroom()} disabled={busy || dirty} title={dirty ? "Save or discard your layout changes first" : undefined}><Plus size={14} /> New classroom</button></div>}
        </div>
        <details style={{ marginTop: 12 }}>
          <summary>Classroom details and capacity</summary>
          <div className="filter-grid" style={{ marginTop: 12 }}>
            <label className="field"><span>Name</span><input value={meta.name} disabled={!canEdit} onChange={(e) => setMeta({ ...meta, name: e.target.value })} maxLength={120} /></label>
            <label className="field"><span>Location label</span><input value={meta.location_label} disabled={!canEdit} onChange={(e) => setMeta({ ...meta, location_label: e.target.value })} maxLength={160} /></label>
            <label className="field"><span>Expected students</span><input type="number" min={0} max={1000} value={meta.total_students} disabled={!canEdit} onChange={(e) => setMeta({ ...meta, total_students: Number(e.target.value) })} /></label>
            <label className="field"><span>Seat capacity</span><input type="number" min={0} max={1000} value={meta.total_seats} disabled={!canEdit} onChange={(e) => setMeta({ ...meta, total_seats: Number(e.target.value) })} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}><span>Description</span><textarea value={meta.description} disabled={!canEdit} onChange={(e) => setMeta({ ...meta, description: e.target.value })} maxLength={2000} /></label>
          </div>
          {canEdit && <button className="button" style={{ marginTop: 12 }} disabled={busy || !meta.name.trim()} onClick={() => void saveMetadata()}>Save classroom details</button>}
        </details>
      </section>

      <div className="editor-layout">
        <section className="chart-card" style={{ minHeight: 0 }} aria-labelledby="editor-heading">
          <h2 id="editor-heading">Layout editor {loadedVersion != null && <span className="badge badge-neutral">from version {loadedVersion}</span>}</h2>
          <div className="editor-toolbar" role="toolbar" aria-label="Editor tools">
            {canEdit && <button className="button secondary small" aria-pressed={tool === "draw"} onClick={() => { setTool("draw"); setSelected(-1); setSelectedVertex(null); }}><PenTool size={14} /> Draw</button>}
            <button className="button secondary small" aria-pressed={tool === "edit"} onClick={() => setTool("edit")}><MousePointer2 size={14} /> Select / edit</button>
            <button className="button secondary small" aria-pressed={tool === "pan"} onClick={() => setTool("pan")}><Hand size={14} /> Pan</button>
            <button className="button secondary small" onClick={() => setView2(zoomView(view, view.zoom * 1.25))} disabled={view.zoom >= MAX_ZOOM} aria-label="Zoom in"><ZoomIn size={14} /></button>
            <button className="button secondary small" onClick={() => setView2(zoomView(view, view.zoom / 1.25))} disabled={view.zoom <= MIN_ZOOM} aria-label="Zoom out"><ZoomOut size={14} /></button>
            <button className="button secondary small" onClick={() => setView(INITIAL_VIEW)} aria-label="Reset zoom"><Maximize2 size={14} /> {Math.round(view.zoom * 100)}%</button>
          </div>
          {tool === "draw" && canEdit && (
            <div className="filter-grid" style={{ marginBottom: 8 }}>
              <label className="field"><span>Region name</span><input value={name} onChange={(e) => setName(e.target.value)} aria-label="Region name" maxLength={120} /></label>
              <label className="field"><span>Region type</span><select value={type} onChange={(e) => setType(e.target.value)} aria-label="Region type">{Object.entries(REGION_STYLE).map(([value, style]) => <option key={value} value={value}>{style.label}</option>)}</select></label>
              <div className="actions"><button className="button small" onClick={finishPolygon} disabled={draft.length < 3}>Finish polygon</button><button className="button secondary small" onClick={() => { setDraft([]); setDrawMessage(""); }} disabled={draft.length === 0}>Cancel</button></div>
            </div>
          )}
          <div role="status" aria-live="polite" className="sr-only">{summary}</div>
          {drawMessage && <p className="field-error" role="alert">{drawMessage}</p>}
          <LayoutCanvas
            regions={regions} selected={selected} selectedVertex={selectedVertex} tool={tool} draft={draft} view={view} imageUrl={imageUrl} heat={heat} invalidKeys={invalidKeys}
            label="Classroom layout canvas. Draw tool: click to add points, Enter to finish, Escape to cancel. Edit tool: use arrow keys to move the selected region or point, plus and minus to zoom."
            onSelectRegion={setSelected} onSelectVertex={setSelectedVertex} onAddDraftPoint={(point) => { setDraft((old) => [...old, point]); setDrawMessage(""); }}
            onCheckpoint={editor.checkpoint} onMoveVertex={(index, vertex, point) => moveVertexTo(index, vertex, point, false)}
            onMoveRegion={(index, dx, dy) => editor.set((old) => old.map((r, i) => (i === index ? { ...r, polygon: movePolygon(r.polygon, dx, dy) } : r)), false)}
            onRemoveVertex={removePoint} onViewChange={setView2} onKeyDown={onCanvasKey}
          />
          <div className="legend" aria-label="Legend">
            {(usedTypes.length ? usedTypes : ["SEAT"]).map((value) => { const style = REGION_STYLE[value] ?? REGION_STYLE.SEAT; return <span key={value}><i style={{ background: "transparent", border: `2px ${style.dash ? "dashed" : "solid"} ${style.color}` }} />{style.label}</span>; })}
            <span><i style={{ background: "transparent", border: "2px dashed var(--danger)" }} />Invalid polygon</span>
          </div>
          <p className="muted">Ctrl + scroll zooms; Ctrl+Z / Ctrl+Y undo and redo. All coordinates stay between 0 and 1, so regions do not depend on the video resolution. No seats or heat maps are generated for you.</p>
        </section>

        <section className="table-card" aria-labelledby="regions-heading">
          <h2 id="regions-heading">Regions ({regions.length})</h2>
          {regions.length === 0 ? <p className="muted">No regions yet. Choose Draw and click on the canvas to outline a seat or zone.</p> : (
            <ul className="match-list" style={{ gap: 8 }}>
              {regions.map((r, i) => (
                <li key={r.region_key} className={`region-row ${i === selected ? "selected" : ""}`}>
                  <button className="button ghost small" style={{ justifyContent: "flex-start" }} aria-pressed={i === selected} onClick={() => { setSelected(i); setSelectedVertex(null); setTool((old) => (old === "draw" ? "edit" : old)); }}>
                    <b>{r.name}</b> · {REGION_STYLE[r.region_type]?.label ?? r.region_type} · {r.polygon.length} pts {invalidKeys.has(r.region_key) && <span className="badge badge-danger">Invalid</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {region && canEdit && (
            <div className="stack" style={{ marginTop: 12 }}>
              <h3 style={{ margin: 0 }}>Edit “{region.name}”</h3>
              <label className="field"><span>Selected region name</span><input value={region.name} maxLength={120} onChange={(e) => updateRegion(selected, { name: e.target.value })} /></label>
              <label className="field"><span>Selected region type</span><select value={region.region_type} onChange={(e) => updateRegion(selected, { region_type: e.target.value })}>{Object.entries(REGION_STYLE).map(([value, style]) => <option key={value} value={value}>{style.label}</option>)}</select></label>
              <label className="chip" style={{ width: "fit-content" }}><input type="checkbox" checked={region.active} onChange={(e) => updateRegion(selected, { active: e.target.checked })} /> Active</label>
              <table className="data-table">
                <caption>Points (normalized 0–1)</caption>
                <thead><tr><th scope="col">#</th><th scope="col">x</th><th scope="col">y</th><th scope="col"><span className="sr-only">Remove</span></th></tr></thead>
                <tbody>
                  {region.polygon.map((p, v) => (
                    <tr key={`${v}-${p.x}-${p.y}`} aria-selected={v === selectedVertex}>
                      <th scope="row" data-th="#"><button className="button ghost small" onClick={() => setSelectedVertex(v)} aria-label={`Select point ${v + 1}`}>{v + 1}</button></th>
                      {(["x", "y"] as const).map((axis) => <td key={axis} data-th={axis}><input aria-label={`Point ${v + 1} ${axis}`} type="number" min={0} max={1} step={0.001} defaultValue={p[axis]} style={{ width: 84 }} onBlur={(e) => { const value = Number(e.target.value); if (Number.isFinite(value) && value !== p[axis]) moveVertexTo(selected, v, { ...p, [axis]: clamp(value) }); }} /></td>)}
                      <td data-th=""><button className="button ghost small" aria-label={`Remove point ${v + 1}`} onClick={() => removePoint(selected, v)}><Trash2 size={13} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="button danger small" onClick={() => setPending({ kind: "delete-region", index: selected })}><Trash2 size={13} /> Delete region…</button>
            </div>
          )}
        </section>
      </div>

      <section className="table-card" aria-labelledby="validation-heading" aria-live="polite">
        <h2 id="validation-heading">Validation</h2>
        {validation.errors.length === 0 && validation.warnings.length === 0 && serverIssues.length === 0 && <p className="muted">{regions.length ? "All polygons are valid and none overlap." : "Nothing to validate yet."}</p>}
        {validation.errors.length > 0 && <div className="banner danger" role="alert"><div><b>Fix before saving:</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{validation.errors.map((issue, i) => <li key={i}>{issue.message}</li>)}</ul></div></div>}
        {validation.warnings.length > 0 && <div className="banner warning" role="status"><div><b>Overlap warnings (saving is allowed):</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{validation.warnings.map((issue, i) => <li key={i}>{issue.message}</li>)}</ul></div></div>}
        {serverIssues.length > 0 && <div className="banner danger" role="alert"><div><b>The server rejected the layout:</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{serverIssues.map((issue, i) => <li key={i}>{issue.message}</li>)}</ul></div></div>}
        {canEdit && <label className="field" style={{ maxWidth: 360, marginTop: 12 }}><span>Name for the next saved version (optional)</span><input value={layoutName} onChange={(e) => setLayoutName(e.target.value)} maxLength={120} placeholder={`Layout ${layouts.length + 1}`} /></label>}
      </section>

      <section className="table-card table-scroll" aria-labelledby="versions-heading">
        <h2 id="versions-heading">Layout versions</h2>
        {layouts.length === 0 ? <p className="muted">No version has been saved for this classroom.</p> : (
          <table className="data-table">
            <caption className="sr-only">Saved layout versions, newest first</caption>
            <thead><tr><th scope="col">Version</th><th scope="col">Name</th><th scope="col">Status</th><th scope="col" className="num">Regions</th><th scope="col">Actions</th></tr></thead>
            <tbody>
              {layouts.map((layout) => (
                <tr key={layout.id}>
                  <th scope="row" data-th="Version">v{layout.version}</th><td data-th="Name">{layout.name}</td>
                  <td data-th="Status">{layout.active ? <StatusBadge status="AVAILABLE" label="Active" /> : <StatusBadge status="STOPPED" label="Inactive" />}{layout.version === loadedVersion && <small>Loaded in editor</small>}</td>
                  <td className="num" data-th="Regions">{layout.regions?.length ?? 0}</td>
                  <td data-th=""><div className="actions">
                    <button className="button secondary small" onClick={() => guarded({ kind: "layout", layout })}>Load into editor</button>
                    {canEdit && layout.active && <button className="button danger small" onClick={() => setPending({ kind: "deactivate", layout })}>Deactivate…</button>}
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted">Saving always creates a new version; earlier versions are kept so old sessions keep the layout they were measured with.</p>
      </section>

      <section className="table-card" aria-labelledby="background-heading">
        <h2 id="background-heading">Background image</h2>
        <p className="muted">A reference photo or video frame to draw over. It is stored for this classroom and used only in the editor.</p>
        <div className="filter-grid">
          {canEdit && <label className="button secondary" style={{ marginTop: 0, cursor: "pointer" }}><Upload size={15} /> Upload reference image<input hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => void uploadReference(e.target.files?.[0])} /></label>}
          <label className="field"><span>Capture from a retained video session</span>
            <select value={sessionId} onChange={(e) => setSessionId(e.target.value)} aria-label="Session for preview and capture"><option value="">Select a session</option>{sessions.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.analytics_mode}</option>)}</select></label>
          <label className="field"><span>At second</span><input type="number" min={0} value={captureAt} onChange={(e) => setCaptureAt(e.target.value)} /></label>
          {canEdit && <div><button className="button secondary" style={{ marginTop: 0 }} onClick={() => void captureReference()} disabled={busy || !sessionId}>Capture frame</button></div>}
        </div>
      </section>

      <section className="table-card" aria-labelledby="preview-heading">
        <h2 id="preview-heading">Preview and heat maps</h2>
        <p className="muted">Uses only stored anonymous observations. Unavailable evidence stays transparent and is never filled with zeros.</p>
        <div className="filter-grid">
          <label className="field"><span>Comparison session</span><select aria-label="Comparison session" value={compareSessionId} onChange={(e) => setCompareSessionId(e.target.value)}><option value="">No comparison</option>{sessions.filter((s) => String(s.id) !== sessionId).map((s) => <option key={s.id} value={s.id}>Compare with {s.name}</option>)}</select></label>
          <label className="field"><span>Metric</span><select value={metric} onChange={(e) => setMetric(e.target.value)}>{HEAT_METRICS.map((v) => <option key={v}>{v}</option>)}</select></label>
          <label className="field"><span>Region</span><select aria-label="Region filter" value={regionFilter} onChange={(e) => setRegionFilter(e.target.value)}><option value="">All regions</option>{regions.map((r) => <option key={r.region_key} value={r.region_key}>{r.name}</option>)}</select></label>
          <label className="field"><span>Start (s)</span><input type="number" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} /></label>
          <label className="field"><span>End (s)</span><input type="number" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} /></label>
          <label className="field"><span>Interval (s)</span><input type="number" min={1} value={range.interval} onChange={(e) => setRange({ ...range, interval: e.target.value })} /></label>
        </div>
        <div className="filter-actions"><button className="button secondary" onClick={() => void refreshPreview()} disabled={!sessionId}>Refresh anonymous preview</button><button className="button" onClick={() => void loadHeatmap()} disabled={!sessionId}>Load heat map</button></div>
        {preview && <div className="notice">Preview only · {preview.status} · {(preview.tracks || []).length} anonymous tracks · matched {(preview.tracks || []).filter((t: any) => t.assignment === "MATCHED").length} · unmatched {(preview.tracks || []).filter((t: any) => t.assignment === "UNMATCHED").length} · excluded {(preview.tracks || []).filter((t: any) => t.assignment === "EXCLUDED").length}</div>}
        {heatmap && <div className="notice">{metric} heat map · {heatmap.status}. Unavailable evidence is transparent, never zero-filled. {heatmap.generated_at ? formatDateTime(heatmap.generated_at) : ""}</div>}
      </section>

      <ConfirmDialog
        open={pending != null} tone={pending?.kind === "layout" || pending?.kind === "classroom" ? "primary" : "danger"}
        title={pending?.kind === "delete-region" ? "Delete this region?" : pending?.kind === "deactivate" ? "Deactivate this layout version?" : "Discard unsaved changes?"}
        description={pending?.kind === "delete-region" ? `“${regions[pending.index]?.name ?? "This region"}” is removed from the draft. You can undo it, and nothing is saved until you save a new version.` : pending?.kind === "deactivate" ? "New sessions will stop using this version. Existing sessions and the saved version itself are kept." : "Your unsaved edits will be lost if you continue."}
        confirmLabel={pending?.kind === "delete-region" ? "Delete region" : pending?.kind === "deactivate" ? "Deactivate" : "Discard and continue"}
        onCancel={() => setPending(null)} onConfirm={() => void perform(pending)}
      />
      <ConfirmDialog open={guard.pendingPath != null} tone="primary" title="Leave without saving?" description="This layout has unsaved changes that will be lost if you leave the page." confirmLabel="Leave page" onCancel={guard.stay} onConfirm={guard.leave} />
    </>
  );
}
