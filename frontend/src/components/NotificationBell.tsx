import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";

type Notification = { id: number; title: string; message: string; read: boolean; category?: string; severity?: string; link?: string | null };
const POLL_MS = 60000;

/**
 * Header bell. The unread count comes from the server (X-Unread-Count) so it stays correct beyond the
 * few notifications previewed here; the full list, filters and bulk actions live on /notifications.
 */
export function NotificationBell() {
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await api.get("/v1/notifications", { params: { page_size: 6 } });
        if (cancelled) return;
        const list: Notification[] = Array.isArray(response.data) ? response.data : [];
        setItems(list);
        const header = Number(response.headers?.["x-unread-count"]);
        setUnread(Number.isFinite(header) ? header : list.filter((item) => !item.read).length);
      } catch { /* the header must not break the shell if notifications are unavailable */ }
    }
    void load();
    const id = window.setInterval(load, POLL_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false); }
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onClick); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function markRead(id: number) {
    try {
      await api.post(`/v1/notifications/${id}/read`);
      setItems((old) => old.map((item) => (item.id === id ? { ...item, read: true } : item)));
      setUnread((count) => Math.max(0, count - 1));
    } catch { /* best-effort; the notifications page reports failures */ }
  }

  return (
    <div className="notif-wrap" ref={wrapRef}>
      <button className="notif-bell" aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"} aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((v) => !v)}>
        <Bell size={17} />
        {unread > 0 && <span className="notif-badge">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="notif-panel" role="dialog" aria-label="Recent notifications">
          <h3>Notifications</h3>
          {items.length === 0 ? (
            <div className="empty">No notifications.</div>
          ) : (
            <ul>
              {items.map((item) => (
                <li key={item.id} style={{ opacity: item.read ? 0.6 : 1 }}>
                  <b>{item.title}</b>
                  <div className="muted">{item.message}</div>
                  <div className="actions" style={{ marginTop: 6 }}>
                    {item.link && <Link className="button secondary small" to={item.link} onClick={() => setOpen(false)}>Open session</Link>}
                    {!item.read && <button className="button secondary small" onClick={() => void markRead(item.id)}>Mark read</button>}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div style={{ padding: "8px 14px", borderTop: "1px solid var(--border)" }}>
            <Link to="/notifications" onClick={() => setOpen(false)}>View all notifications</Link>
          </div>
        </div>
      )}
    </div>
  );
}
