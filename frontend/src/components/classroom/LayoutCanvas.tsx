import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { clamp, type Point } from "../../utils/polygon";

export const WORLD_W = 1000;
export const WORLD_H = 600;
export type EditorRegion = { region_key: string; name: string; region_type: string; polygon: Point[]; active: boolean };
export type View = { zoom: number; x: number; y: number };
export type Tool = "draw" | "edit" | "pan";
export const MIN_ZOOM = 1, MAX_ZOOM = 6;

/** Region types are told apart by stroke pattern as well as colour, so the legend never relies on colour alone. */
export const REGION_STYLE: Record<string, { color: string; dash?: string; label: string }> = {
  SEAT: { color: "var(--chart-2)", label: "Seat" },
  ZONE: { color: "var(--chart-1)", dash: "10 5", label: "Zone" },
  INSTRUCTOR: { color: "var(--chart-4)", dash: "2 5", label: "Instructor area" },
  PROJECTOR: { color: "var(--primary)", dash: "12 4 2 4", label: "Projector / board" },
  ENTRANCE: { color: "var(--info)", dash: "6 6", label: "Entrance" },
  EXIT: { color: "var(--warning)", dash: "6 6", label: "Exit" },
  EXCLUDED: { color: "var(--danger)", label: "Excluded" },
};

export function clampView(view: View): View {
  const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom));
  const width = WORLD_W / zoom, height = WORLD_H / zoom;
  return { zoom, x: Math.max(0, Math.min(WORLD_W - width, view.x)), y: Math.max(0, Math.min(WORLD_H - height, view.y)) };
}
/** Zoom around a world-space anchor so the point under the cursor/centre stays put. */
export function zoomView(view: View, nextZoom: number, anchor: { x: number; y: number } = { x: view.x + WORLD_W / view.zoom / 2, y: view.y + WORLD_H / view.zoom / 2 }): View {
  const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, nextZoom));
  const ratioX = (anchor.x - view.x) / (WORLD_W / view.zoom), ratioY = (anchor.y - view.y) / (WORLD_H / view.zoom);
  return clampView({ zoom, x: anchor.x - ratioX * (WORLD_W / zoom), y: anchor.y - ratioY * (WORLD_H / zoom) });
}

type Drag = { kind: "vertex"; region: number; vertex: number } | { kind: "region"; region: number; last: Point } | { kind: "pan"; startX: number; startY: number; origin: View };

export function LayoutCanvas(props: {
  regions: EditorRegion[]; selected: number; selectedVertex: number | null; tool: Tool; draft: Point[]; view: View; imageUrl: string | null;
  heat: Record<string, number>; invalidKeys: Set<string>; label: string;
  onSelectRegion: (index: number) => void; onSelectVertex: (vertex: number | null) => void; onAddDraftPoint: (point: Point) => void;
  onCheckpoint: () => void; onMoveVertex: (region: number, vertex: number, point: Point) => void; onMoveRegion: (region: number, dx: number, dy: number) => void;
  onRemoveVertex: (region: number, vertex: number) => void; onViewChange: (view: View) => void; onKeyDown: (event: KeyboardEvent) => void;
}) {
  const { regions, selected, selectedVertex, tool, draft, view, imageUrl, heat, invalidKeys, label } = props;
  const drag = useRef<Drag | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const vbW = WORLD_W / view.zoom, vbH = WORLD_H / view.zoom;

  function toNormalized(event: { clientX: number; clientY: number }): Point {
    const box = svgRef.current!.getBoundingClientRect();
    const wx = view.x + ((event.clientX - box.left) / Math.max(box.width, 1)) * vbW;
    const wy = view.y + ((event.clientY - box.top) / Math.max(box.height, 1)) * vbH;
    return { x: Number(clamp(wx / WORLD_W).toFixed(4)), y: Number(clamp(wy / WORLD_H).toFixed(4)) };
  }
  function capture(event: PointerEvent) { svgRef.current?.setPointerCapture?.(event.pointerId); }

  function onCanvasDown(event: PointerEvent<SVGSVGElement>) {
    svgRef.current?.focus();
    if (tool === "draw") { props.onAddDraftPoint(toNormalized(event)); return; }
    if (tool === "pan") { drag.current = { kind: "pan", startX: event.clientX, startY: event.clientY, origin: view }; capture(event); return; }
    props.onSelectRegion(-1); props.onSelectVertex(null);
  }
  function onMove(event: PointerEvent<SVGSVGElement>) {
    const current = drag.current;
    if (!current) return;
    if (current.kind === "pan") {
      const box = svgRef.current!.getBoundingClientRect();
      props.onViewChange(clampView({ ...current.origin, x: current.origin.x - ((event.clientX - current.startX) / Math.max(box.width, 1)) * vbW, y: current.origin.y - ((event.clientY - current.startY) / Math.max(box.height, 1)) * vbH }));
    } else if (current.kind === "vertex") {
      props.onMoveVertex(current.region, current.vertex, toNormalized(event));
    } else {
      const now = toNormalized(event);
      props.onMoveRegion(current.region, now.x - current.last.x, now.y - current.last.y);
      drag.current = { ...current, last: now };
    }
  }
  const endDrag = () => { drag.current = null; };
  function onWheel(event: React.WheelEvent<SVGSVGElement>) {
    if (!event.ctrlKey && !event.metaKey) return; // plain wheel keeps scrolling the page
    event.preventDefault();
    const box = svgRef.current!.getBoundingClientRect();
    const anchor = { x: view.x + ((event.clientX - box.left) / box.width) * vbW, y: view.y + ((event.clientY - box.top) / box.height) * vbH };
    props.onViewChange(zoomView(view, view.zoom * (event.deltaY < 0 ? 1.15 : 1 / 1.15), anchor));
  }
  const strokeUnit = 1 / view.zoom;

  return (
    <div className="canvas-frame">
      <svg
        ref={svgRef} viewBox={`${view.x} ${view.y} ${vbW} ${vbH}`} role="application" tabIndex={0} aria-label={label}
        style={{ aspectRatio: `${WORLD_W} / ${WORLD_H}`, cursor: tool === "draw" ? "crosshair" : tool === "pan" ? "grab" : "default", touchAction: "none" }}
        onPointerDown={onCanvasDown} onPointerMove={onMove} onPointerUp={endDrag} onPointerCancel={endDrag} onWheel={onWheel} onKeyDown={props.onKeyDown}
      >
        <rect x={0} y={0} width={WORLD_W} height={WORLD_H} fill="var(--surface-secondary)" />
        {imageUrl && <image href={imageUrl} x={0} y={0} width={WORLD_W} height={WORLD_H} preserveAspectRatio="xMidYMid meet" />}
        {regions.map((region, index) => {
          const style = REGION_STYLE[region.region_type] ?? REGION_STYLE.SEAT;
          const isSelected = index === selected, isInvalid = invalidKeys.has(region.region_key);
          const points = region.polygon.map((p) => `${p.x * WORLD_W},${p.y * WORLD_H}`).join(" ");
          const centroid = { x: (region.polygon.reduce((s, p) => s + p.x, 0) / region.polygon.length) * WORLD_W, y: (region.polygon.reduce((s, p) => s + p.y, 0) / region.polygon.length) * WORLD_H };
          return (
            <g key={region.region_key} opacity={region.active ? 1 : 0.4}>
              <polygon
                points={points} fill={style.color} fillOpacity={0.14 + (heat[region.region_key] || 0) * 0.55}
                stroke={isInvalid ? "var(--danger)" : isSelected ? "var(--text-primary)" : style.color} strokeWidth={(isSelected ? 4 : 2) * strokeUnit} strokeDasharray={isInvalid ? `${6 * strokeUnit} ${4 * strokeUnit}` : style.dash}
                onPointerDown={(event) => {
                  if (tool !== "edit") return;
                  event.stopPropagation(); props.onSelectRegion(index); props.onSelectVertex(null); props.onCheckpoint(); capture(event);
                  drag.current = { kind: "region", region: index, last: toNormalized(event) };
                }}
              ><title>{`${region.name} (${style.label})${isInvalid ? " — invalid polygon" : ""}`}</title></polygon>
              <text x={centroid.x} y={centroid.y} fontSize={14 * strokeUnit} textAnchor="middle" fill="var(--text-primary)" stroke="var(--surface)" strokeWidth={3 * strokeUnit} paintOrder="stroke" pointerEvents="none">{region.name}</text>
              {isSelected && tool === "edit" && region.polygon.map((p, v) => (
                <circle
                  key={v} cx={p.x * WORLD_W} cy={p.y * WORLD_H} r={(v === selectedVertex ? 11 : 8) * strokeUnit} fill={v === selectedVertex ? "var(--primary)" : "var(--surface)"} stroke="var(--text-primary)" strokeWidth={2 * strokeUnit}
                  onDoubleClick={() => props.onRemoveVertex(index, v)}
                  onPointerDown={(event) => { event.stopPropagation(); props.onSelectVertex(v); props.onCheckpoint(); capture(event); drag.current = { kind: "vertex", region: index, vertex: v }; }}
                ><title>{`Point ${v + 1} (drag to move, double-click to remove)`}</title></circle>
              ))}
            </g>
          );
        })}
        {draft.length > 0 && (
          <g pointerEvents="none">
            <polyline points={draft.map((p) => `${p.x * WORLD_W},${p.y * WORLD_H}`).join(" ")} fill="none" stroke="var(--info)" strokeWidth={3 * strokeUnit} strokeDasharray={`${8 * strokeUnit} ${4 * strokeUnit}`} />
            {draft.map((p, i) => <circle key={i} cx={p.x * WORLD_W} cy={p.y * WORLD_H} r={6 * strokeUnit} fill="var(--info)" />)}
          </g>
        )}
      </svg>
    </div>
  );
}
