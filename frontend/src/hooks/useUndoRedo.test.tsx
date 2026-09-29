// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useUndoRedo } from "./useUndoRedo";

describe("useUndoRedo", () => {
  it("records steps, undoes, redoes, and clears redo history on a new edit", () => {
    const { result } = renderHook(() => useUndoRedo<number[]>([]));
    act(() => result.current.set((old) => [...old, 1]));
    act(() => result.current.set((old) => [...old, 2]));
    expect(result.current.value).toEqual([1, 2]);
    expect(result.current.canUndo).toBe(true);
    act(() => result.current.undo());
    expect(result.current.value).toEqual([1]);
    expect(result.current.canRedo).toBe(true);
    act(() => result.current.redo());
    expect(result.current.value).toEqual([1, 2]);
    act(() => result.current.undo());
    act(() => result.current.set([9]));
    expect(result.current.value).toEqual([9]);
    expect(result.current.canRedo).toBe(false);
  });

  it("treats a whole drag as one step (checkpoint once, then unrecorded frames)", () => {
    const { result } = renderHook(() => useUndoRedo({ x: 0 }));
    act(() => result.current.checkpoint());
    for (const x of [1, 2, 3, 4]) act(() => result.current.set({ x }, false));
    expect(result.current.value).toEqual({ x: 4 });
    act(() => result.current.undo());
    expect(result.current.value).toEqual({ x: 0 });
    expect(result.current.canUndo).toBe(false);
  });

  it("does nothing when there is nothing to undo or redo, and reset clears history", () => {
    const { result } = renderHook(() => useUndoRedo("a"));
    act(() => result.current.undo()); act(() => result.current.redo());
    expect(result.current.value).toBe("a");
    act(() => result.current.set("b"));
    act(() => result.current.reset("z"));
    expect(result.current.value).toBe("z");
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("bounds history to 50 steps", () => {
    const { result } = renderHook(() => useUndoRedo(0));
    for (let i = 1; i <= 60; i++) act(() => result.current.set(i));
    let undos = 0;
    while (result.current.canUndo && undos < 100) { act(() => result.current.undo()); undos++; }
    expect(undos).toBe(50);
    expect(result.current.value).toBe(10);
  });
});
