// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConfirmDialog, Dialog } from "./Dialog";

afterEach(() => { cleanup(); document.body.style.overflow = ""; });

function Opener({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (<><button onClick={() => setOpen(true)}>Open it</button><Dialog open={open} title="Sample dialog" description="Some context" onClose={() => { onClose(); setOpen(false); }}><input aria-label="First field" /><button>Inside action</button></Dialog></>);
}

describe("Dialog", () => {
  it("is a labelled, described, modal dialog that locks scrolling and focuses its content", () => {
    render(<Opener />);
    fireEvent.click(screen.getByText("Open it"));
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByRole("heading", { name: "Sample dialog" })).toBeTruthy();
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
    expect(dialog.getAttribute("aria-describedby")).toBeTruthy();
    expect(document.body.style.overflow).toBe("hidden");
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("closes on Escape and restores focus and scrolling to the opener", () => {
    const onClose = vi.fn();
    render(<Opener onClose={onClose} />);
    const opener = screen.getByText("Open it");
    opener.focus(); fireEvent.click(opener);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
    expect(document.body.style.overflow).toBe("");
  });

  it("traps Tab focus inside the dialog in both directions", () => {
    render(<Opener />);
    fireEvent.click(screen.getByText("Open it"));
    const close = screen.getByLabelText("Close Sample dialog"), last = screen.getByText("Inside action");
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(close); // wraps from last to first
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last); // and back
  });

  it("closes from the close button", () => {
    render(<Opener />);
    fireEvent.click(screen.getByText("Open it"));
    fireEvent.click(screen.getByLabelText("Close Sample dialog"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not steal focus from an input when the parent re-renders", () => {
    function Typing() {
      const [text, setText] = useState("");
      return <Dialog open title="Typing" onClose={() => {}}><input aria-label="Field" value={text} onChange={(e) => setText(e.target.value)} /></Dialog>;
    }
    render(<Typing />);
    const field = screen.getByLabelText("Field") as HTMLInputElement;
    field.focus();
    fireEvent.change(field, { target: { value: "abc" } });
    expect(document.activeElement).toBe(field);
  });
});

describe("ConfirmDialog", () => {
  it("starts focus on Cancel so Enter can never confirm by accident", () => {
    render(<ConfirmDialog open title="Delete?" description="Permanent." confirmLabel="Delete" onConfirm={() => {}} onCancel={() => {}} />);
    expect(document.activeElement).toBe(screen.getByText("Cancel"));
  });

  it("calls the right handler for confirm and cancel", () => {
    const onConfirm = vi.fn(), onCancel = vi.fn();
    render(<ConfirmDialog open title="Delete?" description="Permanent." confirmLabel="Delete" onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByText("Cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1); expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Delete"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("requires the exact typed phrase before a destructive action is enabled", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog open title="Delete session?" description="Permanent." confirmLabel="Delete session" requireText="DELETE" onConfirm={onConfirm} onCancel={() => {}} />);
    const button = screen.getByText("Delete session") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), { target: { value: "delete" } });
    expect(button.disabled).toBe(true); // case-sensitive
    fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), { target: { value: "DELETE" } });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("disables the confirm button while busy", () => {
    render(<ConfirmDialog open busy title="Working" description="x" confirmLabel="Go" onConfirm={() => {}} onCancel={() => {}} />);
    expect((screen.getByText("Working…") as HTMLButtonElement).disabled).toBe(true);
  });
});
