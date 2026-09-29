import {
  Activity, BarChart3, ChevronLeft, ChevronRight, FileText, GitCompare, LayoutDashboard,
  Map, Menu, Monitor, Moon, Radio, Search, Settings, Sun, Upload, Users, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { api } from "../services/api";
import { useTheme, type ThemeMode } from "../theme/ThemeContext";
import { BreadcrumbProvider, BreadcrumbTrail } from "./Breadcrumbs";
import { ConnectionBadge } from "./ConnectionBadge";
import { NotificationBell } from "./NotificationBell";

type NavItem = { to: string; label: string; icon: typeof LayoutDashboard; roles?: Array<"ADMINISTRATOR" | "INSTRUCTOR"> };
const NAV_GROUPS: Array<{ label: string; items: NavItem[] }> = [
  { label: "", items: [{ to: "/dashboard", label: "Overview", icon: LayoutDashboard }] },
  {
    label: "Monitor",
    items: [
      { to: "/live", label: "Live Classroom", icon: Radio },
      { to: "/upload", label: "Upload & Process", icon: Upload, roles: ["ADMINISTRATOR", "INSTRUCTOR"] },
      { to: "/sessions", label: "Sessions", icon: Activity },
    ],
  },
  {
    label: "Analyze",
    items: [
      { to: "/compare", label: "Compare", icon: GitCompare },
      { to: "/analytics-workspace", label: "Analytics", icon: BarChart3 },
      { to: "/aggregate-dashboards", label: "Aggregate Dashboards", icon: BarChart3 },
      { to: "/search", label: "Search", icon: Search },
      { to: "/reports", label: "Reports", icon: FileText },
    ],
  },
  {
    label: "Configure",
    items: [
      { to: "/classroom-setup", label: "Classrooms", icon: Map, roles: ["ADMINISTRATOR", "INSTRUCTOR"] },
      { to: "/management", label: "Management", icon: Users, roles: ["ADMINISTRATOR", "INSTRUCTOR"] },
      { to: "/settings", label: "Settings", icon: Settings, roles: ["ADMINISTRATOR"] },
    ],
  },
];
const COLLAPSE_KEY = "ambisense_nav_collapsed";
const THEME_OPTIONS: Array<{ mode: ThemeMode; icon: typeof Sun; label: string }> = [
  { mode: "light", icon: Sun, label: "Light theme" },
  { mode: "dark", icon: Moon, label: "Dark theme" },
  { mode: "system", icon: Monitor, label: "Match system theme" },
];

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const { can } = useAuth();
  const visibleGroups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.roles || can(...item.roles)),
  })).filter((group) => group.items.length > 0);
  return (
    <nav>
      {visibleGroups.map((group, index) => (
        <div className="nav-group" key={index}>
          {group.label && <div className="nav-group-label">{group.label}</div>}
          {group.items.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} title={label} aria-label={label} onClick={onNavigate} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon size={18} aria-hidden="true" />
              <span className="nav-label">{label}</span>
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

function Brand() {
  return (
    <div className="brand">
      <span aria-hidden="true">A</span>
      <div className="brand-label">
        AMBISENSE
        <small>Ambient intelligence</small>
      </div>
    </div>
  );
}

function ThemeSwitcher() {
  const { mode, setMode } = useTheme();
  return (
    <div className="theme-switch" role="radiogroup" aria-label="Theme">
      {THEME_OPTIONS.map(({ mode: option, icon: Icon, label }) => (
        <button
          key={option}
          role="radio"
          aria-checked={mode === option}
          aria-label={label}
          title={label}
          className={mode === option ? "active" : ""}
          onClick={() => setMode(option)}
        >
          <Icon size={14} aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}

function MobileDrawer({ onClose }: { onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const panel = panelRef.current;
    const focusable = panel?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])');
    focusable?.[0]?.focus();
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab" || !focusable || focusable.length === 0) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [onClose]);
  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <div className="drawer-panel" ref={panelRef} role="dialog" aria-modal="true" aria-label="Navigation">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <Brand />
          <button className="collapse-toggle" onClick={onClose} aria-label="Close navigation">
            <X size={16} />
          </button>
        </div>
        <NavList onNavigate={onClose} />
      </div>
    </>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; } });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [devMode, setDevMode] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  }

  useEffect(() => {
    api.get("/v1/auth/me").then((r) => setDevMode(Boolean(r.data?.auth_enabled === false))).catch(() => {});
  }, []);

  useEffect(() => {
    if (!profileOpen) return;
    function onClick(e: MouseEvent) { if (profileRef.current && !profileRef.current.contains(e.target as Node)) setProfileOpen(false); }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [profileOpen]);

  const initials = (user?.display_name || user?.email || "?").slice(0, 1).toUpperCase();

  return (
    <BreadcrumbProvider>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <div className={`shell ${collapsed ? "collapsed" : ""}`}>
        <aside aria-label="Primary navigation">
          <div style={{ display: "flex", alignItems: "center" }}>
            <Brand />
            <button className="collapse-toggle" onClick={toggleCollapsed} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} aria-pressed={collapsed}>
              {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
            </button>
          </div>
          <NavList />
          <div className="privacy">
            <BarChart3 size={18} aria-hidden="true" />
            <div>
              <b>Privacy first</b>
              <small>Anonymous tracking by default</small>
            </div>
          </div>
        </aside>
        <div className="workspace">
          <header>
            <div className="header-left">
              <button className="hamburger" onClick={() => setDrawerOpen(true)} aria-label="Open navigation menu">
                <Menu size={18} />
              </button>
              <BreadcrumbTrail />
            </div>
            <div className="header-right">
              {devMode && <span className="dev-badge">DEV MODE · AUTH DISABLED</span>}
              <ConnectionBadge />
              <ThemeSwitcher />
              <NotificationBell />
              <div className="profile-menu" ref={profileRef}>
                <button className="profile-trigger" onClick={() => setProfileOpen((v) => !v)} aria-haspopup="true" aria-expanded={profileOpen} aria-label="Account menu">
                  <span className="profile-avatar" aria-hidden="true">{initials}</span>
                  <span style={{ fontSize: 13 }}>{user?.display_name || user?.email}</span>
                </button>
                {profileOpen && (
                  <div className="notif-panel" role="menu">
                    <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)" }}>
                      <small style={{ display: "block", color: "var(--text-muted)" }}>{user?.role}</small>
                      <b>{user?.display_name || user?.email}</b>
                    </div>
                    <div style={{ padding: 10 }}>
                      <button className="button secondary" style={{ width: "100%", justifyContent: "center", marginTop: 0 }} onClick={() => void logout()}>
                        Sign out
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </header>
          <main id="main-content" tabIndex={-1}>
            <Outlet />
          </main>
        </div>
      </div>
      {drawerOpen && <MobileDrawer onClose={() => setDrawerOpen(false)} />}
    </BreadcrumbProvider>
  );
}
