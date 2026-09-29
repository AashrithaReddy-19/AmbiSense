import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Filters with an explicit Apply step. The *applied* filters live in the URL query
 * string (shareable, survives reload); the *draft* is what the form controls edit.
 * Only non-default values are written to the URL, so a pristine page has a clean URL.
 * Keys outside `defaults` (for example `tab` or `ids`) are preserved untouched.
 */
export function useUrlFilters<T extends Record<string, string>>(defaults: T) {
  const [params, setParams] = useSearchParams();
  const keys = useMemo(() => Object.keys(defaults) as Array<keyof T & string>, [defaults]);
  const applied = useMemo(() => {
    const values = { ...defaults };
    for (const key of keys) values[key] = (params.get(key) ?? defaults[key]) as T[typeof key];
    return values;
  }, [params, defaults, keys]);
  const [draft, setDraft] = useState<T>(applied);

  const write = useCallback((values: T, drop: string[] = []) => {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      for (const key of drop) next.delete(key);
      for (const key of keys) {
        if (values[key] === defaults[key] || values[key] === "") next.delete(key);
        else next.set(key, values[key]);
      }
      return next;
    }, { replace: true });
  }, [defaults, keys, setParams]);

  /** `drop` lists extra query keys (for example `page`) to clear in the SAME URL update; two separate updates would overwrite each other. */
  const apply = useCallback((override?: Partial<T>, drop?: string[]) => {
    const values = { ...draft, ...override } as T;
    setDraft(values);
    write(values, drop);
  }, [draft, write]);

  const reset = useCallback((drop?: string[]) => {
    setDraft({ ...defaults });
    write({ ...defaults }, drop);
  }, [defaults, write]);

  /** Write a non-filter query parameter (for example `page` or `tab`) without touching the filters. */
  const setExtra = useCallback((key: string, value: string | null) => {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (value === null || value === "") next.delete(key); else next.set(key, value);
      return next;
    }, { replace: true });
  }, [setParams]);

  const update = useCallback(<K extends keyof T>(key: K, value: T[K]) => setDraft((old) => ({ ...old, [key]: value })), []);
  const activeCount = keys.filter((key) => applied[key] !== defaults[key]).length;
  const dirty = keys.some((key) => draft[key] !== applied[key]);
  return { applied, draft, update, apply, reset, activeCount, dirty, params, setExtra };
}
