import { AlertTriangle, Inbox, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="empty large" role="status">
      <Inbox size={28} aria-hidden="true" />
      <b>{title}</b>
      {description && <span>{description}</span>}
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong", message, code, onRetry,
}: { title?: string; message: string; code?: string; onRetry?: () => void }) {
  return (
    <div className="error-panel" role="alert">
      <h3>
        <AlertTriangle size={16} style={{ verticalAlign: "-3px", marginRight: 6 }} aria-hidden="true" />
        {title}
      </h3>
      <p>{message}</p>
      {code && <code>Reference: {code}</code>}
      {onRetry && (
        <button className="button secondary" onClick={onRetry}>
          <RotateCcw size={14} /> Retry
        </button>
      )}
    </div>
  );
}

export function LoadingSkeleton({ kind = "card", count = 1 }: { kind?: "card" | "row" | "text"; count?: number }) {
  const cls = kind === "row" ? "skeleton-row" : kind === "text" ? "skeleton-text" : "skeleton-card";
  return (
    <div>
      <span className="sr-only" role="status">Loading…</span>
      <div aria-hidden="true">
        {Array.from({ length: count }).map((_, i) => (
          <div className={`skeleton ${cls}`} key={i} style={{ marginBottom: 8 }} />
        ))}
      </div>
    </div>
  );
}
