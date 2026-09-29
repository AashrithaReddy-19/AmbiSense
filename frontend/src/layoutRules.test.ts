import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const workspaceCss = readFileSync(new URL("./workspace.css", import.meta.url), "utf8");

/**
 * jsdom does not lay anything out, so the responsive fixes found by the real-browser audit (scripts/browser_check.py) are
 * pinned here by the rules that produce them. Each assertion names the defect it prevents.
 */
const flat = workspaceCss.replace(/\s+/g, " ");

describe("responsive layout rules found by the browser audit", () => {
  it("clips absolutely positioned table text (sr-only) inside the scroll container so tables never widen the page", () => {
    expect(flat).toMatch(/\.table-scroll, \.table-card \{ position: relative; \}/);
    expect(flat).toMatch(/\.table-scroll \{ overflow-x: auto; \}/);
  });

  it("lets stacked cards shrink below their content width instead of stretching the grid", () => {
    expect(flat).toMatch(/\.stack \{[^}]*grid-template-columns: minmax\(0, 1fr\)/);
  });

  it("keeps every select at least 32px tall (the audit found 23px selects at tablet width)", () => {
    expect(flat).toMatch(/(^|\}| )select \{ min-height: 32px; \}/);
  });

  it("collapses the dashboard split and the upload configuration grid to one column on small screens", () => {
    expect(flat).toMatch(/@media \(max-width: 900px\) \{ \.live-layout\.dash-split \{ grid-template-columns: 1fr; \} \}/);
    expect(flat).toMatch(/@media \(max-width: 600px\) \{ \.settings-grid\.two-up \{ grid-template-columns: 1fr; \} \}/);
  });

  it("pins the notifications panel inside the viewport on phones", () => {
    expect(flat).toMatch(/\.notif-panel \{ position: fixed; left: 8px; right: 8px;[^}]*width: auto; max-width: none;/);
  });

  it("places the consent checkbox before its text without changing the accessible label order", () => {
    expect(flat).toMatch(/\.toggle\.consent \{ display: flex; flex-direction: row-reverse;/);
  });
});
