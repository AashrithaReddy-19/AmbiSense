import { useCallback, useRef, useState } from "react";
import { api } from "./api";

/** Pull the file name out of a Content-Disposition header, falling back to a caller-supplied name. */
export function filenameFromDisposition(header: string | undefined, fallback: string): string {
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header ?? "");
  return match ? decodeURIComponent(match[1]) : fallback;
}

/**
 * Download an API file through axios so the Authorization header is sent (a plain
 * `<a href>` cannot carry the bearer token when authentication is enabled) and so a
 * failure can be reported instead of navigating the browser to a JSON error page.
 * `path` may include or omit the `/api` prefix.
 */
export async function downloadFile(path: string, fallbackName: string): Promise<string> {
  let response;
  try {
    response = await api.get(path.replace(/^\/api(?=\/)/, ""), { responseType: "blob" });
  } catch (error) {
    // With responseType "blob" even JSON error bodies arrive as a Blob; decode it so callers can show the real message.
    const body = (error as { response?: { data?: unknown } }).response;
    if (body?.data instanceof Blob) {
      try { body.data = JSON.parse(await body.data.text()); } catch { body.data = {}; }
    }
    throw error;
  }
  const name = filenameFromDisposition(response.headers?.["content-disposition"] as string | undefined, fallbackName);
  const url = URL.createObjectURL(response.data as Blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return name;
}

/**
 * Guards against duplicate requests: while an action for `key` is in flight, further calls with
 * the same key are ignored, and `busy(key)` lets buttons disable themselves.
 */
export function useInFlight() {
  const active = useRef(new Set<string>());
  const [, force] = useState(0);
  const run = useCallback(async <T,>(key: string, task: () => Promise<T>): Promise<T | undefined> => {
    if (active.current.has(key)) return undefined;
    active.current.add(key); force((n) => n + 1);
    try { return await task(); } finally { active.current.delete(key); force((n) => n + 1); }
  }, []);
  const busy = useCallback((key: string) => active.current.has(key), []);
  return { run, busy };
}
