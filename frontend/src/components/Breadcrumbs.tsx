/* eslint-disable react-hooks/set-state-in-effect -- breadcrumb trail resets its dynamic-label override when the route changes */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

export const ROUTE_LABELS: Record<string, string> = {
  dashboard: "Overview",
  "aggregate-dashboards": "Aggregate Dashboards",
  live: "Live Classroom",
  sessions: "Sessions",
  compare: "Compare",
  upload: "Upload & Process",
  search: "Search",
  reports: "Reports",
  "classroom-setup": "Classrooms",
  management: "Management",
  "analytics-workspace": "Analytics",
  settings: "Settings",
  notifications: "Notifications",
};

const BreadcrumbLabelContext = createContext<(label: string | null) => void>(() => {});

/** Lets a page (e.g. SessionDetail) supply a human-readable label for its
 * dynamic route segment instead of the raw ID, without every page having
 * to render its own breadcrumb markup. */
export function useBreadcrumbLabel(label: string | null | undefined) {
  const setLabel = useContext(BreadcrumbLabelContext);
  useEffect(() => {
    setLabel(label ?? null);
    return () => setLabel(null);
  }, [label, setLabel]);
}

const DynamicLabelValueContext = createContext<string | null>(null);

export function BreadcrumbProvider({ children }: { children: ReactNode }) {
  const [dynamicLabel, setDynamicLabel] = useState<string | null>(null);
  const location = useLocation();
  useEffect(() => setDynamicLabel(null), [location.pathname]);
  return (
    <BreadcrumbLabelContext.Provider value={setDynamicLabel}>
      <DynamicLabelValueContext.Provider value={dynamicLabel}>{children}</DynamicLabelValueContext.Provider>
    </BreadcrumbLabelContext.Provider>
  );
}

/** Renders the actual breadcrumb trail; placed inside the header wherever
 * the shell wants it, separate from BreadcrumbProvider so the provider can
 * wrap the whole shell while the trail renders only in the header. */
export function BreadcrumbTrail() {
  const dynamicLabel = useContext(DynamicLabelValueContext);
  const location = useLocation();
  const segments = location.pathname.split("/").filter(Boolean);
  const crumbs = useMemo(() => {
    const trail: { label: string; to: string | null }[] = [{ label: "Overview", to: segments.length ? "/dashboard" : null }];
    let path = "";
    segments.forEach((segment, index) => {
      path += `/${segment}`;
      const isLast = index === segments.length - 1;
      const isDynamic = /^\d+$/.test(segment);
      const label = isDynamic ? (dynamicLabel || `#${segment}`) : (ROUTE_LABELS[segment] || segment.replace(/-/g, " "));
      if (index === 0 && ROUTE_LABELS[segment] === "Overview") return; // avoid duplicating "Overview"
      trail.push({ label, to: isLast ? null : path });
    });
    return trail;
  }, [segments, dynamicLabel]);

  useEffect(() => {
    const current = crumbs[crumbs.length - 1]?.label;
    document.title = current ? `${current} · AmbiSense` : "AmbiSense";
  }, [crumbs]);

  if (crumbs.length <= 1) return <nav className="breadcrumbs" aria-label="Breadcrumb" />;
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      {crumbs.map((crumb, index) => (
        <span key={index}>
          {index > 0 && <span aria-hidden="true"> / </span>}
          {crumb.to ? <Link to={crumb.to}>{crumb.label}</Link> : <span className="current" aria-current="page">{crumb.label}</span>}
        </span>
      ))}
    </nav>
  );
}
