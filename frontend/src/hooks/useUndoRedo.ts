import { useCallback, useState } from "react";

type History<T> = { past: T[]; present: T; future: T[] };
const LIMIT = 50;

/**
 * Undo/redo for an editable value. `set` records a history step by default; pass `record=false` for the
 * intermediate frames of a drag and call `checkpoint()` once when the drag starts so a whole drag is one step.
 * Updates are pure (no ref mutation inside setState), so they are safe under React StrictMode.
 */
export function useUndoRedo<T>(initial: T) {
  const [history, setHistory] = useState<History<T>>({ past: [], present: initial, future: [] });
  const set = useCallback((next: T | ((previous: T) => T), record = true) => {
    setHistory((state) => {
      const value = typeof next === "function" ? (next as (previous: T) => T)(state.present) : next;
      return record ? { past: [...state.past.slice(-(LIMIT - 1)), state.present], present: value, future: [] } : { ...state, present: value };
    });
  }, []);
  const checkpoint = useCallback(() => setHistory((state) => ({ past: [...state.past.slice(-(LIMIT - 1)), state.present], present: state.present, future: [] })), []);
  const undo = useCallback(() => setHistory((state) => (state.past.length ? { past: state.past.slice(0, -1), present: state.past[state.past.length - 1], future: [state.present, ...state.future] } : state)), []);
  const redo = useCallback(() => setHistory((state) => (state.future.length ? { past: [...state.past, state.present], present: state.future[0], future: state.future.slice(1) } : state)), []);
  const reset = useCallback((value: T) => setHistory({ past: [], present: value, future: [] }), []);
  return { value: history.present, set, checkpoint, undo, redo, reset, canUndo: history.past.length > 0, canRedo: history.future.length > 0 };
}
