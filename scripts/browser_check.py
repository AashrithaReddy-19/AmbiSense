"""Real-browser verification of the dashboard through the Chrome DevTools Protocol (no downloads, no test framework).

    python scripts/browser_check.py --url http://127.0.0.1:5273 --session-id 148 --out browser_report.json

Needs: a local Chrome or Edge, the `websockets` package, and a running dashboard. Point --url at an ISOLATED stack (a copy of
the data, temporary upload/report folders): the interaction checks open dialogs, drive a fake camera and intercept API calls,
and must never run against the database you care about.

Per page, viewport (360/768/1024/1440) and theme (light/dark/system) it records: horizontal overflow, bad text (`—%`, NaN,
undefined, [object Object]), unlabeled controls and nameless buttons, chart accessibility, dark/light text contrast, tap-target
size, privacy-terminology snippets, console errors and failed network requests, and saves a screenshot. It also exercises
keyboard tab navigation, dialog focus trapping and restoration, the mobile drawer and menus, reduced motion, and the loading /
empty / error / unauthorized states by intercepting API responses. `--live` additionally drives the Live page with Chrome's
FAKE camera device (a synthetic pattern, not a physical webcam).
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

VIEWPORTS = [(360, 800), (768, 1024), (1024, 768), (1440, 900)]
PAGES = [("dashboard", "/dashboard"), ("aggregate", "/aggregate-dashboards"), ("live", "/live"), ("upload", "/upload"), ("sessions", "/sessions"),
         ("session-detail", "/sessions/{sid}"), ("analytics", "/analytics-workspace"), ("compare", "/compare?session_ids={sid},{sid2}"), ("reports", "/reports"),
         ("search", "/search"), ("classroom-setup", "/classroom-setup"), ("management", "/management"), ("settings", "/settings"), ("notifications", "/notifications")]
BAD_TEXT = ["—%", "NaN", "undefined", "[object Object]", "Infinity", "null%"]
CHROME_CANDIDATES = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                     r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

AUDIT_JS = r"""
(() => {
  const R = {}; const de = document.documentElement;
  const inClosedDetails = (el) => { for (let p = el.parentElement, prev = el; p; prev = p, p = p.parentElement) { if (p.tagName === 'DETAILS' && !p.open && !(prev.tagName === 'SUMMARY')) return true; } return false; };
  const visible = (el) => { const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none' || inClosedDetails(el)) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sel = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  R.viewport = { inner: innerWidth, client: de.clientWidth, scroll: de.scrollWidth, bodyScroll: document.body.scrollWidth };
  R.horizontalOverflow = de.scrollWidth > de.clientWidth + 1 || document.body.scrollWidth > de.clientWidth + 1;
  R.overflowOffenders = [];
  if (R.horizontalOverflow) {
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect(); if (r.width === 0 || r.right <= de.clientWidth + 1 || !visible(el)) continue;
      let clipped = false;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) { const s = getComputedStyle(p); if (/(auto|scroll|hidden|clip)/.test(s.overflowX) && p.getBoundingClientRect().right <= de.clientWidth + 1) { clipped = true; break; } }
      if (!clipped) { R.overflowOffenders.push(sel(el) + ' right=' + Math.round(r.right)); if (R.overflowOffenders.length >= 8) break; }
    }
  }
  const text = document.body.innerText;
  R.badText = ['—%', 'NaN', 'undefined', '[object Object]', 'Infinity', 'null%'].filter((t) => text.includes(t)).map((t) => { const i = text.indexOf(t); return t + ' … ' + text.slice(Math.max(0, i - 40), i + 40).replace(/\s+/g, ' '); });
  const ctl = [...document.querySelectorAll('input:not([type=hidden]),select,textarea')].filter(visible);
  R.controls = ctl.length;
  R.unlabeled = ctl.filter((el) => { const named = el.getAttribute('aria-label') || el.getAttribute('title') || (el.getAttribute('aria-labelledby') && document.getElementById(el.getAttribute('aria-labelledby'))?.textContent.trim()) || (el.labels && el.labels.length && [...el.labels].some((l) => l.textContent.trim())) || (['button', 'submit'].includes(el.type) && el.value); return !named; }).map((el) => sel(el) + ' [' + (el.type || '') + ' ' + (el.name || el.placeholder || '') + ']').slice(0, 10);
  R.namelessButtons = [...document.querySelectorAll('button,a[href],[role=button],[role=tab],[role=menuitem]')].filter(visible).filter((el) => !((el.getAttribute('aria-label') || el.innerText || el.textContent || el.getAttribute('title') || '').trim() || el.querySelector('img[alt]:not([alt=""])'))).map(sel).slice(0, 10);
  R.imagesWithoutAlt = [...document.querySelectorAll('img:not([alt])')].map(sel).slice(0, 5);
  R.h1 = document.querySelectorAll('h1').length; R.main = document.querySelectorAll('main').length;
  R.title = document.title; R.lang = de.lang; R.theme = de.getAttribute('data-theme'); R.bodyBg = getComputedStyle(document.body).backgroundColor;
  R.charts = [...document.querySelectorAll('.recharts-wrapper')].map((w) => { const img = w.closest('[role=img]'); return { labelled: !!(img && (img.getAttribute('aria-label') || '').length > 10) }; });
  R.tables = document.querySelectorAll('table').length;
  R.privacyTerms = []; const re = /attendance|recogni[sz]|facial|identif|emotion|cheat|lazy|bored/gi; let m;
  while ((m = re.exec(text)) && R.privacyTerms.length < 12) R.privacyTerms.push(text.slice(Math.max(0, m.index - 60), m.index + 70).replace(/\s+/g, ' '));
  if (innerWidth <= 800) {
    R.smallTargets = [...document.querySelectorAll('button,a[href],input:not([type=hidden]),select,[role=tab]')].filter(visible).filter((el) => { const r = el.getBoundingClientRect(); return (r.width < 24 || r.height < 24) && !(el.tagName === 'A' && el.closest('p,li,small,td,span,div.muted') && r.height >= 14 && el.closest('p,li,small,td')); }).map((el) => sel(el) + ' ' + Math.round(el.getBoundingClientRect().width) + 'x' + Math.round(el.getBoundingClientRect().height)).slice(0, 10);
  }
  const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (fg, bg) => { const a = fg[3]; return [fg[0] * a + bg[0] * (1 - a), fg[1] * a + bg[1] * (1 - a), fg[2] * a + bg[2] * (1 - a), 1]; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
  const hex = (c) => '#' + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const bgOf = (el) => { const stack = []; for (let p = el; p; p = p.parentElement) { const s = getComputedStyle(p); if (s.backgroundImage !== 'none') return null; const c = rgba(s.backgroundColor); if (c[3] > 0) { stack.push(c); if (c[3] >= 0.999) break; } } let base = [255, 255, 255, 1]; for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base); return base; };
  const seen = new Set(); const fails = []; let checked = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode() && checked < 700) {
    const node = walker.currentNode; if (!node.textContent.trim()) continue; const el = node.parentElement;
    if (!el || seen.has(el) || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName) || el.closest('[hidden],[aria-hidden=true],.sr-only,.recharts-wrapper') || !visible(el) || el.closest(':disabled')) continue;
    seen.add(el); const s = getComputedStyle(el); if (parseFloat(s.opacity) < 0.5) continue;
    const bg = bgOf(el); if (!bg) continue; checked++;
    const fg = over(rgba(s.color), bg); const size = parseFloat(s.fontSize); const large = size >= 24 || (size >= 18.66 && parseInt(s.fontWeight, 10) >= 700);
    const r = ratio(fg, bg); if (r < (large ? 3 : 4.5)) fails.push({ el: sel(el), text: node.textContent.trim().slice(0, 40), ratio: Math.round(r * 100) / 100, fg: hex(fg), bg: hex(bg) });
  }
  R.contrast = { checked, failureCount: fails.length, failures: fails.slice(0, 12) };
  return R;
})()
"""


FOCUS_JS = r"""
(() => {
  const el = document.activeElement; if (!el || el === document.body) return { visible: false, contrast: null, tag: 'body' };
  const s = getComputedStyle(el); const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (fg, bg) => { const a = fg[3]; return [fg[0] * a + bg[0] * (1 - a), fg[1] * a + bg[1] * (1 - a), fg[2] * a + bg[2] * (1 - a), 1]; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const bgOf = (n) => { const stack = []; for (let p = n; p; p = p.parentElement) { const c = rgba(getComputedStyle(p).backgroundColor); if (c[3] > 0) { stack.push(c); if (c[3] >= 0.999) break; } } let base = [255, 255, 255, 1]; for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base); return base; };
  const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2 ? s.outlineColor : null;
  const shadow = s.boxShadow && s.boxShadow !== 'none' ? (s.boxShadow.match(/(rgba?\([^)]*\)|color\([^)]*\))/) || [])[1] : null;
  const colour = outline || shadow; if (!colour) return { visible: false, contrast: null, tag: el.tagName.toLowerCase() + '.' + String(el.className).slice(0, 30) };
  const fg = rgba(colour); const bg = bgOf(el.parentElement || el); const l1 = lum(over(fg, bg)), l2 = lum(bg);
  return { visible: true, contrast: Math.round(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)) * 100) / 100, tag: el.tagName.toLowerCase() };
})()
"""


class CdpError(RuntimeError):
    pass


class PageTimeout(CdpError):
    """A page or step used up its time budget; the run records it and moves on."""


class Page:
    def __init__(self, ws_url):
        self.ws = connect(ws_url, max_size=None, open_timeout=15)
        self.next_id = 0
        self.console, self.failures, self.pending, self.rules, self.held = [], [], set(), [], []
        self.script_ids = []
        self.deadline = None

    def _check_deadline(self):
        if self.deadline is not None and time.time() > self.deadline:
            raise PageTimeout("time budget exceeded")

    # -- protocol plumbing ----------------------------------------------------------------------------------------
    def send(self, method, timeout=60, **params):
        self.next_id += 1
        mid = self.next_id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        end = time.time() + timeout
        while True:
            self._check_deadline()
            self._release_held()
            remaining = end - time.time()
            if remaining <= 0:
                raise CdpError(f"timeout waiting for {method}")
            try:
                message = json.loads(self.ws.recv(timeout=min(remaining, 0.5)))
            except TimeoutError:
                continue
            if message.get("id") == mid:
                if "error" in message:
                    raise CdpError(f"{method}: {message['error']}")
                return message.get("result", {})
            self._event(message)

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self._check_deadline()
            self._release_held()
            try:
                self._event(json.loads(self.ws.recv(timeout=min(0.1, max(0.01, end - time.time())))))
            except TimeoutError:
                continue

    def _fulfill(self, request_id, rule):
        body = json.dumps(rule.get("body", {})).encode()
        headers = [{"name": "Content-Type", "value": "application/json"}, {"name": "Access-Control-Allow-Origin", "value": "*"}]
        self.ws.send(json.dumps({"id": self._bump(), "method": "Fetch.fulfillRequest", "params": {"requestId": request_id, "responseCode": rule.get("status", 200), "responseHeaders": headers, "body": base64.b64encode(body).decode()}}))

    def _bump(self):
        self.next_id += 1
        return self.next_id

    def _release_held(self):
        now = time.time()
        for item in [h for h in self.held if h[0] <= now]:
            self.held.remove(item)
            self._fulfill(item[1], item[2])

    def _event(self, message):
        method, params = message.get("method"), message.get("params", {})
        if method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "warning", "assert"):
            text = " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", []))
            self.console.append({"level": params["type"], "text": text[:300]})
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            self.console.append({"level": "exception", "text": (details.get("exception", {}).get("description") or details.get("text", ""))[:300]})
        elif method == "Log.entryAdded" and params.get("entry", {}).get("level") in ("error", "warning"):
            entry = params["entry"]
            self.console.append({"level": "log-" + entry["level"], "text": f"{entry.get('text', '')} {entry.get('url', '')}"[:300]})
        elif method == "Network.requestWillBeSent":
            self.pending.add(params["requestId"])
        elif method == "Network.responseReceived":
            if params["response"]["status"] >= 400:
                self.failures.append({"url": params["response"]["url"], "status": params["response"]["status"]})
        elif method in ("Network.loadingFinished",):
            self.pending.discard(params["requestId"])
        elif method == "Network.loadingFailed":
            self.pending.discard(params["requestId"])
            if not params.get("canceled"):
                self.failures.append({"url": params.get("requestId"), "status": params.get("errorText")})
        elif method == "Fetch.requestPaused":
            request_id, url = params["requestId"], params["request"]["url"]
            for rule in self.rules:
                if re.search(rule["pattern"], url):
                    if rule.get("delay"):
                        self.held.append((time.time() + rule["delay"], request_id, rule))
                    else:
                        self._fulfill(request_id, rule)
                    return
            self.ws.send(json.dumps({"id": self._bump(), "method": "Fetch.continueRequest", "params": {"requestId": request_id}}))

    # -- conveniences ---------------------------------------------------------------------------------------------
    def js(self, expression):
        result = self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise CdpError(str(result["exceptionDetails"].get("exception", {}).get("description", result["exceptionDetails"])))
        return result["result"].get("value")

    def viewport(self, width, height):
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=width < 600)

    def set_theme(self, mode, os_scheme="light", reduced_motion=False):
        for script_id in self.script_ids:
            self.send("Page.removeScriptToEvaluateOnNewDocument", identifier=script_id)
        self.script_ids = [self.send("Page.addScriptToEvaluateOnNewDocument", source=f"try{{localStorage.setItem('ambisense_theme','{mode}')}}catch(e){{}}")["identifier"]]
        features = [{"name": "prefers-color-scheme", "value": os_scheme}, {"name": "prefers-reduced-motion", "value": "reduce" if reduced_motion else "no-preference"}]
        self.send("Emulation.setEmulatedMedia", features=features)

    def goto(self, url, settle_max=30):
        self.send("Page.navigate", url=url)
        self.pump(0.4)
        end = time.time() + 15
        while time.time() < end and self.js("document.readyState") != "complete":
            self.pump(0.2)
        self.settle(settle_max)

    def settle(self, maximum=30):
        end, stable = time.time() + maximum, 0
        while time.time() < end and stable < 3:
            self.pump(0.25)
            busy = self.js("!!document.querySelector('.skeleton,.skeleton-row,[aria-busy=true],.state[role=status]')")
            stable = stable + 1 if (not self.pending and not busy) else 0
        self.pump(0.3)

    def key(self, key, code, vk, modifiers=0):
        for kind in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", type=kind, key=key, code=code, windowsVirtualKeyCode=vk, nativeVirtualKeyCode=vk, modifiers=modifiers)
        self.pump(0.15)

    def screenshot(self, path):
        metrics = self.send("Page.getLayoutMetrics")
        size = metrics.get("cssContentSize") or metrics["contentSize"]
        clip = {"x": 0, "y": 0, "width": size["width"], "height": min(size["height"], 3200), "scale": 1}
        data = self.send("Page.captureScreenshot", format="png", clip=clip, captureBeyondViewport=True)["data"]
        Path(path).write_bytes(base64.b64decode(data))

    def take_events(self):
        events = {"console": self.console[:], "network": self.failures[:]}
        self.console.clear(); self.failures.clear()
        return events

    def intercept(self, rules):
        self.rules = rules
        self.send("Fetch.enable", patterns=[{"urlPattern": "*/api/*"}])

    def stop_intercepting(self):
        self.rules = []
        self.send("Fetch.disable")


def launch_chrome(exe, port, profile, fake_camera):
    args = [exe, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--window-size=1440,900", "--hide-scrollbars=false"]
    if fake_camera:
        args += ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
    process = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                version = json.load(response)["Browser"]
            break
        except OSError:
            time.sleep(0.5)
    else:
        process.kill()
        raise SystemExit("Chrome did not start")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
        target = next(t for t in json.load(response) if t.get("type") == "page")
    page = Page(target["webSocketDebuggerUrl"])
    for domain in ("Page", "Runtime", "Network", "Log"):
        page.send(f"{domain}.enable")
    return process, page, version


class guarded:
    """Run one page or step under a time budget. A timeout or error is recorded as a finding and the run continues."""

    def __init__(self, page, report, label, budget):
        self.page, self.report, self.label, self.budget = page, report, label, budget

    def __enter__(self):
        self.page.deadline = time.time() + self.budget
        return self

    def __exit__(self, kind, error, traceback):
        self.page.deadline = None
        if error is None:
            return False
        if isinstance(error, KeyboardInterrupt):
            return False
        finding = {"page": self.label, "viewport": None, "theme": None, "kind": "page-timeout" if isinstance(error, PageTimeout) else "step-error", "detail": f"{type(error).__name__}: {str(error)[:300]}"}
        self.report["findings"].append(finding)
        self.report.setdefault("errors", []).append(finding)
        log_progress(self.report, {"event": "guard", **finding})
        return True   # swallow: the remaining pages and steps still run


def log_progress(report, entry):
    path = report.get("_progress_path")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": round(time.time(), 1), **entry}) + "\n")


def significant(events):
    """Console/network noise that is not a finding: cancelled navigations and the favicon."""
    console = [c for c in events["console"] if "favicon" not in c["text"]]
    network = [n for n in events["network"] if "favicon" not in str(n["url"])]
    return console, network


def issues_of(audit, viewport_width):
    found = []
    if audit["horizontalOverflow"]:
        found.append(("overflow", f"scrollWidth {audit['viewport']['scroll']} > {audit['viewport']['client']}: {audit['overflowOffenders']}"))
    for item in audit["badText"]:
        found.append(("bad-text", item))
    for item in audit["unlabeled"]:
        found.append(("unlabeled-control", item))
    for item in audit["namelessButtons"]:
        found.append(("nameless-button", item))
    for item in audit["imagesWithoutAlt"]:
        found.append(("image-alt", item))
    if audit["h1"] != 1:
        found.append(("h1-count", str(audit["h1"])))
    if audit["main"] != 1:
        found.append(("main-count", str(audit["main"])))
    if audit["charts"] and not all(c["labelled"] for c in audit["charts"]):
        found.append(("chart-unlabelled", str(audit["charts"])))
    if audit["charts"] and audit["tables"] == 0:
        found.append(("chart-no-table-alternative", "chart present but no table on the page"))
    for item in audit.get("smallTargets", []):
        found.append(("small-target", item))
    if audit["contrast"]["failureCount"]:
        found.append(("contrast", f"{audit['contrast']['failureCount']} of {audit['contrast']['checked']}: {audit['contrast']['failures'][:4]}"))
    return found


def step_00_system_theme_follows_the_os_preference(page, args, report, record, shots, profile, sid, sid2):
    """system theme follows the OS preference"""
    # ---- system theme follows the OS preference ---------------------------------------------------------------------------------
    system = []
    for scheme in ("light", "dark"):
        page.set_theme("system", scheme)
        page.viewport(1024, 768)
        for name, path in (("dashboard", "/dashboard"), ("sessions", "/sessions"), ("settings", "/settings")):
            page.take_events()
            page.goto(args.url + path)
            audit = page.js(AUDIT_JS)
            channels = [int(v) for v in re.findall(r"\d+", audit["bodyBg"])[:3]]
            looks_dark = sum(channels) / 3 < 100
            system.append({"page": name, "os_scheme": scheme, "data_theme_attribute": audit["theme"], "body_background": audit["bodyBg"], "renders_dark": looks_dark, "contrast_failures": audit["contrast"]["failureCount"], "issues": [k for k, _ in issues_of(audit, 1024)]})
            if name == "dashboard":
                page.screenshot(shots / f"dashboard_1024_system-{scheme}.png")
            record(name, (1024, 768), f"system/{scheme}", audit, page.take_events())
    report["interactions"]["system_theme"] = {"results": system, "ok": all(r["renders_dark"] == (r["os_scheme"] == "dark") for r in system)}


def step_01_system_mode_reacts_to_a_runtime_os_schem(page, args, report, record, shots, profile, sid, sid2):
    """system mode reacts to a runtime OS-scheme change without a reload"""
    # ---- system mode reacts to a runtime OS-scheme change without a reload -----------------------------------------------------
    page.set_theme("system", "light"); page.viewport(1024, 768); page.goto(args.url + "/dashboard")
    bg = lambda: [int(v) for v in re.findall(r"\d+", page.js("getComputedStyle(document.body).backgroundColor"))[:3]]
    light_bg = bg()
    page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}, {"name": "prefers-reduced-motion", "value": "no-preference"}]); page.pump(0.6)
    dark_bg = bg()
    page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}, {"name": "prefers-reduced-motion", "value": "no-preference"}]); page.pump(0.6)
    back_bg = bg()
    report["interactions"]["runtime_scheme_change"] = {"light": light_bg, "after_dark": dark_bg, "after_light_again": back_bg,
                                                        "ok": sum(light_bg) > 600 and sum(dark_bg) < 300 and sum(back_bg) > 600 and page.js("document.documentElement.getAttribute('data-theme')") is None}


def step_02_root_route_redirects_to_the_dashboard(page, args, report, record, shots, profile, sid, sid2):
    """root route redirects to the dashboard"""
    # ---- root route redirects to the dashboard ---------------------------------------------------------------------------------
    page.set_theme("light"); page.goto(args.url + "/")
    report["interactions"]["root_redirect"] = {"path": page.js("location.pathname"), "ok": page.js("location.pathname") == "/dashboard"}


def step_03_visible_focus_indicators_tab_through_the(page, args, report, record, shots, profile, sid, sid2):
    """visible focus indicators: Tab through the first controls of key pages"""
    # ---- visible focus indicators: Tab through the first controls of key pages --------------------------------------------------
    focus = {}
    for name, path in (("dashboard", "/dashboard"), ("sessions", "/sessions"), ("upload", "/upload"), ("settings", "/settings")):
        page.viewport(1024, 768); page.goto(args.url + path)
        page.js("document.body.focus(); window.scrollTo(0, 0)")
        samples = []
        for _ in range(8):
            page.key("Tab", "Tab", 9)
            samples.append(page.js(FOCUS_JS))
        focus[name] = {"samples": len(samples), "without_indicator": [s for s in samples if not s["visible"]], "min_contrast": min([s["contrast"] for s in samples if s["contrast"]] or [99])}
    report["interactions"]["focus_indicators"] = {"pages": focus, "ok": all(not v["without_indicator"] and v["min_contrast"] >= 3 for v in focus.values())}


def step_04_very_long_unbroken_names_must_wrap_or_tr(page, args, report, record, shots, profile, sid, sid2):
    """very long, unbroken names must wrap or truncate, never widen the page"""
    # ---- very long, unbroken names must wrap or truncate, never widen the page --------------------------------------------------
    page.viewport(360, 800)
    real = page.js("fetch('/api/v1/sessions?page_size=5').then(r => r.json())")
    long_name = "Lecture_recording_" + "x" * 150 + "_final_version.mp4"
    for row in real["items"]:
        row["name"] = long_name
    page.intercept([{"pattern": r"/api/v1/sessions\?", "status": 200, "body": real}])
    page.goto(args.url + "/sessions")
    long_audit = page.js(AUDIT_JS)
    page.screenshot(shots / "long_names_sessions_360.png")
    page.stop_intercepting(); page.take_events()
    report["interactions"]["long_names"] = {"overflow": long_audit["horizontalOverflow"], "offenders": long_audit["overflowOffenders"], "name_shown": page.js("document.body.innerText.includes('Lecture_recording_')"), "ok": not long_audit["horizontalOverflow"]}


def step_05_upload_choose_a_file_so_the_configuratio(page, args, report, record, shots, profile, sid, sid2):
    """upload: choose a file so the configuration grid renders, then check it collapses on phones"""
    # ---- upload: choose a file so the configuration grid renders, then check it collapses on phones -----------------------------
    sample = Path(profile) / "sample_clip.mp4"
    sample.write_bytes(bytes(4096))
    upload = {}
    for width, height in ((360, 800), (1024, 768)):
        page.viewport(width, height); page.goto(args.url + "/upload")
        root = page.send("DOM.getDocument", depth=1)["root"]["nodeId"]
        node = page.send("DOM.querySelector", nodeId=root, selector="input[type=file]")["nodeId"]
        page.send("DOM.setFileInputFiles", files=[str(sample)], nodeId=node)
        page.pump(1.0); page.settle(10)
        audit = page.js(AUDIT_JS)
        tracks = page.js("(() => { const g = document.querySelector('.settings-grid.two-up'); return g ? getComputedStyle(g).gridTemplateColumns.split(' ').length : null; })()")
        page.screenshot(shots / f"upload_with_file_{width}.png")
        upload[str(width)] = {"grid_columns": tracks, "overflow": audit["horizontalOverflow"], "issues": [k for k, _ in issues_of(audit, width)]}
        record("upload+file", (width, height), "light", audit, page.take_events())
    report["interactions"]["upload_configuration_grid"] = {**upload, "ok": bool(upload["360"]["grid_columns"] == 1 and upload["1024"]["grid_columns"] == 2 and not upload["360"]["overflow"] and not upload["1024"]["overflow"])}


def step_06_keyboard_tabs(page, args, report, record, shots, profile, sid, sid2):
    """keyboard: tabs"""
    # ---- keyboard: tabs -------------------------------------------------------------------------------------------------------
    page.set_theme("light"); page.viewport(1440, 900); page.goto(f"{args.url}/sessions/{sid}")
    count = page.js("document.querySelectorAll('[role=tab]').length")
    page.js("document.querySelector('[role=tab][aria-selected=true]').focus()")
    first = page.js("document.activeElement.textContent.trim()")
    trace = []
    for key, code, vk in (("ArrowRight", "ArrowRight", 39), ("ArrowRight", "ArrowRight", 39), ("ArrowLeft", "ArrowLeft", 37), ("End", "End", 35), ("Home", "Home", 36)):
        page.key(key, code, vk)
        trace.append({"key": key, **page.js("({focus: document.activeElement.textContent.trim(), selected: document.querySelector('[role=tab][aria-selected=true]').textContent.trim(), sameElement: document.activeElement === document.querySelector('[role=tab][aria-selected=true]'), tabindexes: [...document.querySelectorAll('[role=tab]')].filter(t => t.tabIndex === 0).length})")})
    last_label = page.js("[...document.querySelectorAll('[role=tab]')].pop().textContent.trim()")
    roving = all(t["sameElement"] and t["tabindexes"] == 1 for t in trace)   # focus follows selection; only one tab is in the tab order
    report["interactions"]["tabs_keyboard"] = {"tab_count": count, "start": first, "trace": trace, "roving_tabindex_and_focus_follow_selection": roving,
                                               "ok": bool(count >= 2 and roving and trace[0]["focus"] != first and trace[3]["focus"] == last_label and trace[4]["focus"] == first)}


def step_07_dialog_focus_trapped_then_restored(page, args, report, record, shots, profile, sid, sid2):
    """dialog: focus trapped, then restored"""
    # ---- dialog: focus trapped, then restored -----
    page.set_theme("light"); page.viewport(1440, 900); page.goto(f"{args.url}/sessions/{sid}")
    page.js("document.querySelector('[role=tab]').focus()")
    opened = page.js("(() => { const b = [...document.querySelectorAll('button')].find(x => /^\\s*Delete/.test(x.textContent) && !x.disabled); if (!b) return false; b.focus(); b.click(); return true; })()")
    page.pump(0.5)
    dialog = {"opened": opened}
    if opened:
        dialog["aria"] = page.js("(() => { const d = document.querySelector('[role=dialog]'); return d ? {modal: d.getAttribute('aria-modal'), label: d.getAttribute('aria-label') || d.getAttribute('aria-labelledby')} : null; })()")
        dialog["focus_inside_on_open"] = page.js("!!document.activeElement.closest('[role=dialog]')")
        inside = []
        for _ in range(8):
            page.key("Tab", "Tab", 9)
            inside.append(page.js("!!document.activeElement.closest('[role=dialog]')"))
        for _ in range(3):
            page.key("Tab", "Tab", 9, modifiers=8)
            inside.append(page.js("!!document.activeElement.closest('[role=dialog]')"))
        dialog["tab_cycle_stays_inside"] = all(inside)
        rect = page.js("(() => { const r = document.querySelector('[role=dialog]').getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: innerWidth, h: innerHeight}; })()")
        dialog["within_viewport"] = rect["l"] >= 0 and rect["t"] >= 0 and rect["r"] <= rect["w"] and rect["b"] <= rect["h"]
        page.key("Escape", "Escape", 27)
        dialog["closed_on_escape"] = page.js("!document.querySelector('[role=dialog]')")
        dialog["focus_restored_to_trigger"] = page.js("/^\\s*Delete/.test(document.activeElement.textContent)")
    dialog["ok"] = bool(opened and dialog.get("focus_inside_on_open") and dialog.get("tab_cycle_stays_inside") and dialog.get("closed_on_escape") and dialog.get("focus_restored_to_trigger"))
    report["interactions"]["dialog_focus"] = dialog
    # the same dialog at phone width must not be clipped
    page.viewport(360, 800); page.goto(f"{args.url}/sessions/{sid}")
    page.js("[...document.querySelectorAll('button')].find(x => /^\\s*Delete/.test(x.textContent) && !x.disabled).click()"); page.pump(0.5)
    rect = page.js("(() => { const d = document.querySelector('[role=dialog]'); if (!d) return null; const r = d.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: innerWidth, h: innerHeight}; })()")
    page.screenshot(shots / "dialog_360.png")
    report["interactions"]["dialog_at_360"] = {"rect": rect, "ok": bool(rect and rect["l"] >= 0 and rect["r"] <= rect["w"] and rect["t"] >= 0 and rect["b"] <= rect["h"] + 1)}
    page.key("Escape", "Escape", 27)


def step_08_mobile_navigation_drawer_and_menus(page, args, report, record, shots, profile, sid, sid2):
    """mobile navigation drawer and menus"""
    # ---- mobile navigation drawer and menus ------------------------------------------------------------------------------------
    page.viewport(360, 800); page.goto(args.url + "/dashboard")
    nav = {"hamburger_visible": page.js("(() => { const b = document.querySelector('button[aria-label=\"Open navigation menu\"]'); return !!b && b.getBoundingClientRect().width > 0; })()")}
    page.js("document.querySelector('button[aria-label=\"Open navigation menu\"]').click()"); page.pump(0.6)
    nav["drawer"] = page.js("(() => { const d = document.querySelector('[role=dialog][aria-label=Navigation]'); if (!d) return null; const r = d.getBoundingClientRect(); const links = [...d.querySelectorAll('a')].map(a => { const q = a.getBoundingClientRect(); return {t: a.textContent.trim(), inside: q.left >= 0 && q.right <= innerWidth && q.width > 0}; }); return {modal: d.getAttribute('aria-modal'), within: r.left >= 0 && r.right <= innerWidth, links: links.length, clipped: links.filter(l => !l.inside).map(l => l.t), focusInside: !!document.activeElement.closest('[role=dialog]')}; })()")
    page.screenshot(shots / "mobile_drawer_360.png")
    page.js("[...document.querySelectorAll('[role=dialog][aria-label=Navigation] a')].find(a => /Sessions/.test(a.textContent)).click()"); page.pump(1.0); page.settle(15)
    nav["navigated_to"] = page.js("location.pathname"); nav["drawer_closed_after_navigation"] = page.js("!document.querySelector('[role=dialog][aria-label=Navigation]')")
    page.js("document.querySelector('button[aria-label=\"Open navigation menu\"]').click()"); page.pump(0.4); page.key("Escape", "Escape", 27)
    nav["drawer_closes_on_escape"] = page.js("!document.querySelector('[role=dialog][aria-label=Navigation]')")
    menus = {}
    for label in ("Account menu", "Notifications"):
        found = page.js(f"(() => {{ const b = document.querySelector('button[aria-label^=\"{label}\"]'); if (!b) return false; b.click(); return true; }})()")
        page.pump(0.5)
        menus[label] = {"opened": found, "panel": page.js("(() => { const p = document.querySelector('.notif-panel,[role=menu],.profile-panel,.profile-menu > div'); if (!p) return null; const r = p.getBoundingClientRect(); return {l: r.left, r: r.right, w: innerWidth, within: r.left >= 0 && r.right <= innerWidth}; })()")}
        if found:
            page.screenshot(shots / f"menu_{label.split()[0].lower()}_360.png")
            page.key("Escape", "Escape", 27); page.js("document.body.click()")
    nav["menus"] = menus
    menus_inside = all((m["panel"] or {}).get("within") for m in menus.values() if m["opened"])
    nav["menus_within_viewport"] = menus_inside
    nav["ok"] = bool(menus_inside and nav["hamburger_visible"] and nav["drawer"] and nav["drawer"]["within"] and not nav["drawer"]["clipped"] and nav["navigated_to"] == "/sessions" and nav["drawer_closed_after_navigation"] and nav["drawer_closes_on_escape"])
    report["interactions"]["mobile_navigation"] = nav


def step_09_reduced_motion(page, args, report, record, shots, profile, sid, sid2):
    """reduced motion"""
    # ---- reduced motion --------------------------------------------------------------------------------------------------------
    page.set_theme("light", "light", reduced_motion=True); page.viewport(1024, 768)
    motion = []
    for name, path in (("dashboard", "/dashboard"), ("live", "/live"), ("sessions", "/sessions")):
        page.goto(args.url + path)
        motion.append({"page": name, "animated": page.js("[...document.querySelectorAll('*')].filter(e => { const s = getComputedStyle(e); return (s.animationName !== 'none' && parseFloat(s.animationDuration) > 0.05 && s.animationIterationCount !== '1') || parseFloat(s.transitionDuration) > 0.05; }).slice(0, 6).map(e => e.tagName.toLowerCase() + '.' + String(e.className).slice(0, 30) + ' ' + getComputedStyle(e).animationDuration + '/' + getComputedStyle(e).transitionDuration)"),
                       "smooth_scroll": page.js("getComputedStyle(document.documentElement).scrollBehavior === 'smooth'")})
    report["interactions"]["reduced_motion"] = {"results": motion, "ok": all(not m["animated"] and not m["smooth_scroll"] for m in motion)}
    page.set_theme("light", "light")


def step_10_states_via_response_interception(page, args, report, record, shots, profile, sid, sid2):
    """states via response interception"""
    # ---- states via response interception ------------------------------------------------------------------------------------
    states = {}
    page.viewport(1024, 768)
    page.take_events()
    page.intercept([{"pattern": r"/api/v1/sessions\?", "status": 500, "body": {"detail": "Injected failure", "error": {"code": "INJECTED", "message": "Injected failure for the error-state check", "request_id": "browser-check"}}}])
    page.goto(args.url + "/sessions")
    states["error"] = {"message_shown": page.js("document.body.innerText.includes('Injected failure')"), "retry_button": page.js("!![...document.querySelectorAll('button')].find(b => /retry/i.test(b.textContent))")}
    page.screenshot(shots / "state_error_sessions_1024.png")
    page.rules = []
    page.js("[...document.querySelectorAll('button')].find(b => /retry/i.test(b.textContent))?.click()"); page.settle(15)
    states["error"]["retry_recovers"] = page.js("document.querySelectorAll('tbody tr').length > 0")
    page.intercept([{"pattern": r"/api/v1/sessions\?", "status": 200, "body": {"items": [], "page": 1, "pages": 1, "total": 0}}])
    page.goto(args.url + "/sessions")
    states["empty"] = {"message_shown": page.js("document.body.innerText.includes('No sessions found')")}
    page.screenshot(shots / "state_empty_sessions_1024.png")
    page.intercept([{"pattern": r"/api/v1/sessions\?", "status": 200, "delay": 4, "body": {"items": [], "page": 1, "pages": 1, "total": 0}}])
    page.send("Page.navigate", url=args.url + "/sessions"); page.pump(1.5)
    states["loading"] = {"skeleton_visible": page.js("document.querySelectorAll('.skeleton-row,.skeleton').length > 0")}
    page.screenshot(shots / "state_loading_sessions_1024.png"); page.pump(4)
    page.intercept([{"pattern": r"/api/v1/settings/catalog", "status": 403, "body": {"detail": "Administrator permission required", "error": {"code": "FORBIDDEN", "message": "Administrator permission required", "request_id": "browser-check"}}}])
    page.goto(args.url + "/settings")
    states["unauthorized"] = {"message_shown": page.js("document.body.innerText.includes('Only administrators can view settings')"), "no_form_rendered": page.js("document.querySelectorAll('input,select').length === 0 || !document.querySelector('[role=tablist]')")}
    page.screenshot(shots / "state_unauthorized_settings_1024.png")
    page.intercept([{"pattern": rf"/api/sessions/{sid}/artifacts|/api/v1/sessions/{sid}/artifacts", "status": 500, "body": {"detail": "Artifacts unavailable"}}])
    page.goto(f"{args.url}/sessions/{sid}")
    states["partial"] = {"page_still_renders": page.js("!!document.querySelector('h1') && document.querySelectorAll('[role=tab]').length > 1"), "no_crash_text": page.js("!document.body.innerText.includes('Something went wrong')")}
    page.stop_intercepting()
    page.take_events()
    for value in states.values():
        value["ok"] = all(v for v in value.values() if isinstance(v, bool))
    report["states"] = states


STEPS = [step_00_system_theme_follows_the_os_preference, step_01_system_mode_reacts_to_a_runtime_os_schem, step_02_root_route_redirects_to_the_dashboard, step_03_visible_focus_indicators_tab_through_the, step_04_very_long_unbroken_names_must_wrap_or_tr, step_05_upload_choose_a_file_so_the_configuratio, step_06_keyboard_tabs, step_07_dialog_focus_trapped_then_restored, step_08_mobile_navigation_drawer_and_menus, step_09_reduced_motion, step_10_states_via_response_interception]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:5273")
    parser.add_argument("--backend", default="http://127.0.0.1:8100", help="API the dashboard proxies to (used only for the --live checks).")
    parser.add_argument("--session-id", type=int, default=None, help="A COMPLETED session to open in Session Details (default: discovered through --backend).")
    parser.add_argument("--second-session-id", type=int, default=None, help="Second COMPLETED session for Comparison (default: same as --session-id + first other).")
    parser.add_argument("--out", default="browser_report.json")
    parser.add_argument("--shots", default=None, help="Directory for screenshots.")
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--browser", default=None)
    parser.add_argument("--live", action="store_true", help="Also drive the Live page with Chrome's FAKE camera and check the session completes.")
    parser.add_argument("--quick", action="store_true", help="Light theme at 360 and 1440 only.")
    parser.add_argument("--viewports", default="360,768,1024,1440", help="Comma-separated widths to audit (run shards in parallel with different values).")
    parser.add_argument("--themes", default="light,dark", help="Explicit themes for the matrix.")
    parser.add_argument("--phases", default="matrix,interactions", help="matrix, interactions (system theme, focus, dialog, drawer, motion, states, upload).")
    parser.add_argument("--page-budget", type=int, default=120, help="Seconds one page (load, audit, screenshot, tabs) may take.")
    parser.add_argument("--step-budget", type=int, default=300, help="Seconds one interaction step may take.")
    args = parser.parse_args()

    exe = args.browser or next((c for c in CHROME_CANDIDATES if os.path.exists(c)), None)
    if not exe:
        raise SystemExit("No local Chrome or Edge found; use the manual checklist in docs/DEMO_GUIDE.md instead.")
    shots = Path(args.shots or tempfile.mkdtemp(prefix="ambisense_shots_"))
    shots.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="ambisense_chrome_")
    process, page, version = launch_chrome(exe, args.port, profile, args.live)
    sid, sid2 = args.session_id, args.second_session_id
    if sid is None:
        with urllib.request.urlopen(args.backend + '/api/sessions', timeout=15) as response:
            done = [r for r in json.load(response) if r['status'] == 'COMPLETED' and not r['is_test'] and r['source_type'] == 'VIDEO']
        done.sort(key=lambda r: r['id'], reverse=True)
        if len(done) < 2:
            raise SystemExit('Need two completed non-test video sessions (pass --session-id/--second-session-id).')
        sid, sid2 = done[0]['id'], done[1]['id']
    sid2 = sid2 or sid
    phases = set(args.phases.split(","))
    if args.quick:
        args.viewports, args.themes = "360,1440", "light"
    report = {"browser": version, "url": args.url, "session_ids": [sid, sid2], "shard": {"viewports": args.viewports, "themes": args.themes, "phases": args.phases},
              "matrix": [], "interactions": {}, "states": {}, "findings": [], "_progress_path": args.out + ".progress.jsonl", "status": "running"}
    Path(report["_progress_path"]).write_text("", encoding="utf-8")
    log_progress(report, {"event": "start", "shard": report["shard"]})

    def record(name, viewport, theme, audit, events):
        console, network = significant(events)
        found = issues_of(audit, viewport[0])
        entry = {"page": name, "viewport": viewport[0], "theme": theme, "resolved_theme": audit["theme"], "issues": found, "console": console, "network": network,
                 "privacy_terms": audit["privacyTerms"], "controls": audit["controls"], "charts": len(audit["charts"]), "tables": audit["tables"], "contrast_checked": audit["contrast"]["checked"]}
        report["matrix"].append(entry)
        log_progress(report, {"event": "audit", "page": name, "viewport": viewport[0], "theme": theme, "issues": [k for k, _ in found], "console": len(console), "network": len(network)})
        for kind, detail in found:
            report["findings"].append({"page": name, "viewport": viewport[0], "theme": theme, "kind": kind, "detail": detail})
        for item in console:
            report["findings"].append({"page": name, "viewport": viewport[0], "theme": theme, "kind": "console-" + item["level"], "detail": item["text"]})
        for item in network:
            report["findings"].append({"page": name, "viewport": viewport[0], "theme": theme, "kind": "network-failure", "detail": f"{item['status']} {item['url']}"})

    try:
        all_themes = {"light": ("light", "light"), "dark": ("dark", "light")}
        chosen_themes = [all_themes[t] for t in args.themes.split(",") if t in all_themes]
        chosen_viewports = [v for v in VIEWPORTS if str(v[0]) in args.viewports.split(",")]
        if "matrix" in phases:
            for theme, scheme in chosen_themes:
                page.set_theme(theme, scheme)
                for viewport in chosen_viewports:
                    page.viewport(*viewport)
                    for name, path in PAGES:
                        with guarded(page, report, f"{name}@{viewport[0]}/{theme}", args.page_budget):
                            page.take_events()
                            page.goto(args.url + path.format(sid=sid, sid2=sid2))
                            audit = page.js(AUDIT_JS)
                            page.screenshot(shots / f"{name}_{viewport[0]}_{theme}.png")
                            record(name, viewport, theme, audit, page.take_events())
                            tabs = page.js("[...document.querySelectorAll('[role=tab]')].map(t => t.textContent.trim())")
                            for index, label in enumerate(tabs[1:], start=1):
                                with guarded(page, report, f"{name}#{label}@{viewport[0]}/{theme}", args.page_budget):
                                    page.js(f"document.querySelectorAll('[role=tab]')[{index}].click()")
                                    page.settle(15)
                                    tab_audit = page.js(AUDIT_JS)
                                    safe = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:24]
                                    if viewport[0] in (360, 1440) and theme == "light":
                                        page.screenshot(shots / f"{name}-{safe}_{viewport[0]}_{theme}.png")
                                    record(f"{name}#{label}", viewport, theme, tab_audit, page.take_events())
        if "interactions" in phases:
            for step in STEPS:
                with guarded(page, report, step.__name__, args.step_budget):
                    step(page, args, report, record, shots, profile, sid, sid2)
        # ---- optional: live page with Chrome's fake camera device -------------------------------------------------------------------
        if args.live:
            report["interactions"]["live_fake_camera"] = drive_live(page, args, shots)
    except BaseException as error:   # includes KeyboardInterrupt: the partial report must still say what happened
        report["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        report["status_detail"] = f"{type(error).__name__}: {str(error)[:300]}"
        raise
    else:
        report["status"] = "completed"
    finally:
        report["screenshots"] = str(shots)
        report["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        log_progress(report, {"event": "end", "status": report["status"]})
        Path(args.out).write_text(json.dumps({k: v for k, v in report.items() if k != "_progress_path"}, indent=2), encoding="utf-8")
        try:
            page.ws.close()
        finally:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            shutil.rmtree(profile, ignore_errors=True)
    summarise(report)


def drive_live(page, args, shots):
    def api(path):
        with urllib.request.urlopen(args.backend + path, timeout=10) as response:
            return json.load(response)
    result = {"note": "Chrome FAKE camera device (synthetic pattern) - not a physical webcam."}
    before = {row["id"] for row in api("/api/sessions")}
    page.set_theme("light"); page.viewport(1024, 768); page.take_events()
    page.goto(args.url + "/live")
    clicked = page.js("(() => { const b = [...document.querySelectorAll('button')].find(x => /start|begin/i.test(x.textContent) && !x.disabled); if (!b) return null; const t = b.textContent.trim(); b.click(); return t; })()")
    result["start_button"] = clicked
    session = None
    end = time.time() + 150
    while time.time() < end and not session:
        page.pump(1.0)
        rows = [r for r in api("/api/sessions") if r["id"] not in before and r["source_type"] == "LIVE"]
        session = rows[0] if rows else None
    if not session:
        result["ok"] = False; result["error"] = "no live session was created"
        return result
    result["session_id"] = session["id"]
    frames = 0
    while time.time() < end and frames < 3:
        page.pump(2.0)
        current = api(f"/api/sessions/{session['id']}")
        frames = current["processed_frames"]
        result["status_while_running"] = current["status"]
    result["frames_processed"] = frames
    page.screenshot(shots / "live_running_1024.png")
    result["page_text_has_bad_values"] = page.js("['—%','NaN','undefined','[object Object]'].filter(t => document.body.innerText.includes(t))")
    result["connection_label"] = page.js("(document.querySelector('.live-dot')||{}).textContent")
    page.js("[...document.querySelectorAll('button')].find(x => /stop camera/i.test(x.textContent))?.click()")
    final = None
    stop_end = time.time() + 90
    while time.time() < stop_end:
        page.pump(2.0)
        final = api(f"/api/sessions/{session['id']}")
        if final["status"] in ("COMPLETED", "FAILED"):
            break
    result["final_status"] = final["status"] if final else None
    result["events"] = page.take_events()
    result["ok"] = bool(clicked and frames >= 1 and final and final["status"] == "COMPLETED")
    return result


def summarise(report):
    counts = {}
    for finding in report["findings"]:
        counts[finding["kind"]] = counts.get(finding["kind"], 0) + 1
    print(f"\nBrowser: {report['browser']} | audits: {len(report['matrix'])} | findings: {len(report['findings'])}")
    for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:<28} {count}")
    for name, value in report["interactions"].items():
        print(f"  interaction {name:<22} ok={value.get('ok')}")
    for name, value in report["states"].items():
        print(f"  state       {name:<22} ok={value.get('ok')}")
    print(f"Report: {report.get('out', '')}Screenshots: {report['screenshots']}")


if __name__ == "__main__":
    sys.exit(main())
