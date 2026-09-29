/* eslint-disable react-hooks/set-state-in-effect -- a remote list synchronizes with its query and reloads on demand */
import { useCallback, useEffect, useRef, useState } from "react";
import { apiProblem, type ApiProblem } from "../constants";

export type ListResult<T> = { items: T[]; total: number | null };
export type ListState = "loading" | "ok" | "error" | "forbidden";

/**
 * Loads a list whenever `query` changes. A stale response (an older query resolving after a newer one)
 * is discarded, and `reload()` refetches with the current query without changing it.
 */
export function useRemoteList<T>(fetcher: () => Promise<ListResult<T>>, query: unknown) {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [state, setState] = useState<ListState>("loading");
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [tick, setTick] = useState(0);
  const latest = useRef(fetcher);
  useEffect(() => { latest.current = fetcher; });
  const key = JSON.stringify(query);
  useEffect(() => {
    let cancelled = false;
    setState("loading");
    latest.current()
      .then((result) => { if (cancelled) return; setItems(result.items); setTotal(result.total); setState("ok"); })
      .catch((error) => { if (cancelled) return; const failure = apiProblem(error, "The list could not be loaded."); setProblem(failure); setState(failure.status === 403 ? "forbidden" : "error"); });
    return () => { cancelled = true; };
  }, [key, tick]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { items, total, state, problem, reload };
}
