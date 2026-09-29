import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>;
}

export function PageHeader({
  title, description, actions,
}: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

/** A count/stat card with an explicit loading state and a title attribute
 * carrying the explanatory tooltip - never fabricates a 0 while loading. */
export function StatCard({
  label, value, unit, icon: Icon, tone = "info", loading, tooltip, context,
}: {
  label: string; value: string | number | null; unit?: string; icon: LucideIcon;
  tone?: "success" | "warning" | "danger" | "info" | "violet"; loading?: boolean; tooltip?: string; context?: string;
}) {
  return (
    <article className="metric" title={tooltip}>
      <div className={`metric-icon ${tone}`}>
        <Icon size={19} aria-hidden="true" />
      </div>
      <small>{label}</small>
      {loading ? (
        <div className="skeleton skeleton-text" style={{ width: "60%", height: 27, margin: "4px 0" }} />
      ) : (
        <strong>
          {value == null ? <span style={{ color: "var(--text-muted)", fontSize: 16 }}>Unavailable</span> : value}
          {value != null && unit && <em> {unit}</em>}
        </strong>
      )}
      {context && !loading && <span>{context}</span>}
    </article>
  );
}
