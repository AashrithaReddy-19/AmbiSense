// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { TabPanel, Tabs } from "./Tabs";

afterEach(cleanup);
const TABS = [{ id: "one", label: "One" }, { id: "two", label: "Two", badge: 3 }, { id: "three", label: "Three" }];
function Harness({ keepMounted = false }: { keepMounted?: boolean }) {
  const [active, setActive] = useState("one");
  return (<><Tabs tabs={TABS} active={active} onChange={setActive} label="Sections" /><TabPanel id="one" active={active} keepMounted={keepMounted}>Panel one</TabPanel><TabPanel id="two" active={active} keepMounted={keepMounted}>Panel two</TabPanel></>);
}

describe("Tabs (WAI-ARIA)", () => {
  it("exposes tablist, tab and tabpanel roles with matching ids and a roving tabindex", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Sections" })).toBeTruthy();
    const [one, two] = screen.getAllByRole("tab");
    expect(one.getAttribute("aria-selected")).toBe("true");
    expect(two.getAttribute("aria-selected")).toBe("false");
    expect(one.getAttribute("tabindex")).toBe("0");
    expect(two.getAttribute("tabindex")).toBe("-1");
    const panel = screen.getByRole("tabpanel");
    expect(panel.getAttribute("aria-labelledby")).toBe(one.id);
    expect(one.getAttribute("aria-controls")).toBe(panel.id);
    expect(screen.getByText("3")).toBeTruthy(); // badge
  });

  it("moves selection and focus with arrow keys, wrapping at both ends, plus Home and End", () => {
    render(<Harness />);
    const tab = (name: string) => screen.getByRole("tab", { name: new RegExp(`^${name}`) });
    fireEvent.keyDown(tab("One"), { key: "ArrowRight" });
    expect(tab("Two").getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tab("Two"));
    fireEvent.keyDown(tab("Two"), { key: "ArrowRight" });
    fireEvent.keyDown(tab("Three"), { key: "ArrowRight" });
    expect(tab("One").getAttribute("aria-selected")).toBe("true"); // wraps forward
    fireEvent.keyDown(tab("One"), { key: "ArrowLeft" });
    expect(tab("Three").getAttribute("aria-selected")).toBe("true"); // wraps backward
    fireEvent.keyDown(tab("Three"), { key: "Home" });
    expect(tab("One").getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab("One"), { key: "End" });
    expect(tab("Three").getAttribute("aria-selected")).toBe("true");
  });

  it("mounts only the active panel by default", () => {
    render(<Harness />);
    expect(screen.getByText("Panel one")).toBeTruthy();
    expect(screen.queryByText("Panel two")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: /^Two/ }));
    expect(screen.queryByText("Panel one")).toBeNull();
    expect(screen.getByText("Panel two")).toBeTruthy();
  });

  it("can keep visited panels mounted but hidden so returning does not reload them", () => {
    render(<Harness keepMounted />);
    fireEvent.click(screen.getByRole("tab", { name: /^Two/ }));
    const hidden = screen.getByText("Panel one", { selector: "div" });
    expect(hidden.hasAttribute("hidden")).toBe(true);
    expect(hidden.getAttribute("tabindex")).toBe("-1");
    expect(screen.getByText("Panel two").hasAttribute("hidden")).toBe(false);
  });
});
