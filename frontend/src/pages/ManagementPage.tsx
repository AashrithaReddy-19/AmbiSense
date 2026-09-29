import { ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AccessPanel } from "../components/management/AccessPanel";
import { ClassroomsPanel } from "../components/management/ClassroomsPanel";
import { CoursesPanel } from "../components/management/CoursesPanel";
import { UsersPanel } from "../components/management/UsersPanel";
import { EmptyState } from "../components/States";
import { TabPanel, Tabs, type TabDefinition } from "../components/Tabs";
import { api } from "../services/api";

/**
 * Users, courses, classrooms and access in one place. The API enforces every permission; the tabs a role cannot
 * use are replaced with an explanation instead of silently disappearing.
 */
export function ManagementPage() {
  const { user, can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);
  const isAdmin = can("ADMINISTRATOR");
  const canManage = can("ADMINISTRATOR", "INSTRUCTOR");
  useEffect(() => {
    api.get("/v1/auth/me").then((r) => setAuthEnabled(Boolean(r.data?.auth_enabled))).catch(() => setAuthEnabled(null));
  }, []);
  const tabs = useMemo<TabDefinition[]>(() => [
    { id: "courses", label: "Courses" }, { id: "classrooms", label: "Classrooms" }, { id: "users", label: "Users" }, { id: "access", label: "Access & permissions" },
  ], []);
  const requested = params.get("tab");
  const active = tabs.some((tab) => tab.id === requested) ? (requested as string) : "courses";
  const select = (tab: string) => setParams((previous) => { const next = new URLSearchParams(previous); if (tab === "courses") next.delete("tab"); else next.set("tab", tab); return next; }, { replace: true });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Classrooms, courses &amp; access</h1>
          <p>Aggregate academic context without student identity. Roles decide who can see and change what.</p>
        </div>
      </div>
      {authEnabled === false && (
        <div className="banner warning" role="alert">
          <ShieldAlert size={18} aria-hidden="true" />
          <div><b>Development mode: authentication is disabled.</b> Every request acts as a local administrator, so role checks below are not being applied. Set AUTH_ENABLED=true with a strong AUTH_SECRET_KEY before exposing this instance to anyone else.</div>
        </div>
      )}
      <Tabs tabs={tabs} active={active} onChange={select} label="Management sections" idPrefix="mgmt" />
      <TabPanel id="courses" active={active} idPrefix="mgmt">
        {canManage ? <CoursesPanel canListUsers={isAdmin} /> : <EmptyState title="Course management needs the instructor or administrator role" description="Ask an administrator if you need to create courses or share sessions with reviewers." />}
      </TabPanel>
      <TabPanel id="classrooms" active={active} idPrefix="mgmt">
        {canManage ? <ClassroomsPanel /> : <EmptyState title="Classroom management needs the instructor or administrator role" description="You can still view classrooms wherever they are used." />}
      </TabPanel>
      <TabPanel id="users" active={active} idPrefix="mgmt">
        {isAdmin ? <UsersPanel selfId={user?.id ?? null} /> : <EmptyState title="Only administrators manage user accounts" description="Administrators create accounts and assign roles. You can review what each role may do under Access & permissions." />}
      </TabPanel>
      <TabPanel id="access" active={active} idPrefix="mgmt"><AccessPanel /></TabPanel>
    </>
  );
}
