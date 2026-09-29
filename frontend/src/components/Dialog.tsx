import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Accessible modal: role=dialog + aria-modal, labelled by its title, traps Tab, closes on
 * Escape and backdrop click, locks page scroll, and restores focus to the opener on close.
 * `variant="drawer"` docks it to the right edge (used for report details).
 */
export function Dialog({ open, title, onClose, children, variant = "modal", description }: { open: boolean; title: string; onClose: () => void; children: ReactNode; variant?: "modal" | "drawer"; description?: string }) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  // Keep the latest onClose without re-running the focus/scroll-lock effect on every parent render
  // (which would steal focus from an input the user is typing in).
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusables = () => Array.from(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    (panel.current?.querySelector<HTMLElement>("[data-autofocus]") ?? focusables()[0])?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") { event.stopPropagation(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      opener?.focus?.();
    };
  }, [open]);
  if (!open) return null;
  return (
    <>
      <div className="drawer-overlay" onClick={onClose} aria-hidden="true" />
      <div className={variant === "drawer" ? "dialog dialog-drawer" : "dialog"} ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={description ? descriptionId : undefined}>
        <div className="dialog-head">
          <h2 id={titleId}>{title}</h2>
          <button className="collapse-toggle" onClick={onClose} aria-label={`Close ${title}`}><X size={16} /></button>
        </div>
        {description && <p id={descriptionId} className="muted" style={{ marginTop: 0 }}>{description}</p>}
        <div className="dialog-body">{children}</div>
      </div>
    </>
  );
}

/**
 * Confirmation for destructive or sensitive actions. Focus starts on Cancel so an accidental
 * Enter never confirms. `requireText` (e.g. the session name or "DELETE") forces a typed match.
 */
export function ConfirmDialog({ open, title, description, confirmLabel = "Confirm", tone = "danger", requireText, busy, onConfirm, onCancel, children }: { open: boolean; title: string; description: string; confirmLabel?: string; tone?: "danger" | "primary"; requireText?: string; busy?: boolean; onConfirm: () => void; onCancel: () => void; children?: ReactNode }) {
  const [typed, setTyped] = useState("");
  const armed = !requireText || typed.trim() === requireText;
  return (
    <Dialog open={open} title={title} description={description} onClose={onCancel}>
      {children}
      {requireText && (
        <label className="field">
          <span>Type <b>{requireText}</b> to confirm</span>
          <input value={typed} onChange={(event) => setTyped(event.target.value)} autoComplete="off" aria-label={`Type ${requireText} to confirm`} />
        </label>
      )}
      <div className="actions" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        <button className="button secondary" style={{ marginTop: 0 }} data-autofocus onClick={onCancel}>Cancel</button>
        <button className={tone === "danger" ? "button danger" : "button"} style={{ marginTop: 0 }} disabled={!armed || busy} onClick={() => { onConfirm(); setTyped(""); }}>{busy ? "Working…" : confirmLabel}</button>
      </div>
    </Dialog>
  );
}
