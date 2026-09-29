import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";

type ConnState = "checking" | "connected" | "degraded" | "disconnected";
const POLL_MS = 30000;

/** Polls the real /health endpoint; never claims "Connected" before the
 * first successful response. One request in flight at a time, paused
 * while the tab is hidden, with bounded exponential backoff on failure. */
export function ConnectionBadge() {
  const [state, setState] = useState<ConnState>("checking");
  const inFlight = useRef(false);
  const failures = useRef(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      if (inFlight.current || document.visibilityState === "hidden") { schedule(POLL_MS); return; }
      inFlight.current = true;
      const started = performance.now();
      try {
        const response = await api.get("/health", { timeout: 5000 });
        if (cancelled) return;
        failures.current = 0;
        const slow = performance.now() - started > 2000;
        setState(response.data?.status === "ok" ? (slow ? "degraded" : "connected") : "degraded");
        schedule(POLL_MS);
      } catch {
        if (cancelled) return;
        failures.current += 1;
        setState("disconnected");
        schedule(Math.min(POLL_MS, 4000 * 2 ** Math.min(failures.current, 3)));
      } finally {
        inFlight.current = false;
      }
    }
    function schedule(delay: number) {
      if (cancelled) return;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(check, delay);
    }
    void check();
    const onVisible = () => { if (document.visibilityState === "visible") void check(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { cancelled = true; if (timerRef.current) window.clearTimeout(timerRef.current); document.removeEventListener("visibilitychange", onVisible); };
  }, []);

  const label = { checking: "Checking…", connected: "Connected", degraded: "Degraded", disconnected: "Disconnected" }[state];
  return (
    <span className={`conn-badge ${state}`} role="status" aria-label={`Backend connection: ${label}`}>
      <span className="conn-dot" aria-hidden="true" />
      {label}
    </span>
  );
}
