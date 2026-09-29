import { useRef, type KeyboardEvent, type ReactNode } from "react";

export type TabDefinition = { id: string; label: string; badge?: string | number | null };

/**
 * WAI-ARIA tabs with automatic activation: Arrow Left/Right move (and wrap), Home/End jump,
 * only the selected tab is in the tab order (roving tabindex). Panels are rendered by the
 * caller inside <TabPanel> so only the active panel's content is mounted.
 */
export function Tabs({ tabs, active, onChange, label, idPrefix = "tab" }: { tabs: TabDefinition[]; active: string; onChange: (id: string) => void; label: string; idPrefix?: string }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  function move(index: number) {
    const target = tabs[(index + tabs.length) % tabs.length];
    onChange(target.id);
    refs.current[target.id]?.focus();
  }
  function onKeyDown(event: KeyboardEvent, index: number) {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") { event.preventDefault(); move(index + 1); }
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") { event.preventDefault(); move(index - 1); }
    else if (event.key === "Home") { event.preventDefault(); move(0); }
    else if (event.key === "End") { event.preventDefault(); move(tabs.length - 1); }
  }
  return (
    <div className="tablist" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            ref={(node) => { refs.current[tab.id] = node; }}
            role="tab"
            id={`${idPrefix}-${tab.id}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            className={`tab ${selected ? "active" : ""}`}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {tab.label}
            {tab.badge != null && <span className="tab-badge">{tab.badge}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** `keepMounted` keeps an already-rendered panel in the DOM (hidden) so returning to a tab never re-fetches its data. */
export function TabPanel({ id, active, children, idPrefix = "tab", keepMounted = false }: { id: string; active: string; children: ReactNode; idPrefix?: string; keepMounted?: boolean }) {
  const selected = id === active;
  if (!selected && !keepMounted) return null;
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-${id}`} tabIndex={selected ? 0 : -1} hidden={!selected} className="tabpanel">
      {children}
    </div>
  );
}
