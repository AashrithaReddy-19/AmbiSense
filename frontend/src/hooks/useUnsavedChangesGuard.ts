import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

/**
 * Warns before unsaved work is lost. Covers tab close/refresh (browser prompt) and in-app link clicks
 * (returns the blocked path so the caller can show a confirmation dialog). The browser Back button is
 * not intercepted because the app uses a non-data router.
 */
export function useUnsavedChangesGuard(dirty: boolean) {
  const navigate = useNavigate();
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as HTMLElement | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!anchor || anchor.target === "_blank" || anchor.origin !== window.location.origin) return;
      const path = anchor.pathname + anchor.search + anchor.hash;
      if (path === window.location.pathname + window.location.search + window.location.hash) return;
      event.preventDefault();
      event.stopPropagation();
      setPendingPath(path);
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", onClick, true);
    return () => { window.removeEventListener("beforeunload", beforeUnload); document.removeEventListener("click", onClick, true); };
  }, [dirty]);
  const stay = useCallback(() => setPendingPath(null), []);
  const leave = useCallback(() => { const path = pendingPath; setPendingPath(null); if (path) navigate(path); }, [pendingPath, navigate]);
  return { pendingPath, stay, leave };
}
