import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import { UploadPage } from './pages/UploadPage';
import { SessionsPage } from './pages/SessionsPage';
import { SearchPage } from './pages/SearchPage';
import { LivePage } from './pages/LivePage';
import { LoginPage } from './pages/LoginPage';
import { useAuth } from './auth/AuthContext';

// Heavier, less-frequently-entered pages are route-level code-split so the
// initial bundle only pays for the shell + the default Overview route.
const ReportsPage = lazy(() => import('./pages/ReportsPage').then((m) => ({ default: m.ReportsPage })));
const ClassroomSetupPage = lazy(() => import('./pages/ClassroomSetupPage').then((m) => ({ default: m.ClassroomSetupPage })));
const ManagementPage = lazy(() => import('./pages/ManagementPage').then((m) => ({ default: m.ManagementPage })));
const AnalyticsWorkspacePage = lazy(() => import('./pages/AnalyticsWorkspacePage').then((m) => ({ default: m.AnalyticsWorkspacePage })));
const AggregateDashboardPage = lazy(() => import('./pages/AggregateDashboardPage').then((m) => ({ default: m.AggregateDashboardPage })));
const SessionDetail = lazy(() => import('./pages/SessionDetail').then((m) => ({ default: m.SessionDetail })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const NotificationsPage = lazy(() => import('./pages/NotificationsPage').then((m) => ({ default: m.NotificationsPage })));
const SessionComparePage = lazy(() => import('./pages/SessionComparePage').then((m) => ({ default: m.SessionComparePage })));

function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <main className="login-page">Loading secure workspace…</main>;
  return user ? <Layout /> : <Navigate to="/login" replace />;
}

function RouteFallback() {
  return <div className="state" role="status" aria-live="polite">Loading page…</div>;
}

export default function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<Protected />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="aggregate-dashboards" element={<Suspense fallback={<RouteFallback />}><AggregateDashboardPage /></Suspense>} />
        <Route path="live" element={<LivePage />} />
        <Route path="sessions" element={<SessionsPage />} />
        <Route path="sessions/:id" element={<Suspense fallback={<RouteFallback />}><SessionDetail /></Suspense>} />
        <Route path="compare" element={<Suspense fallback={<RouteFallback />}><SessionComparePage /></Suspense>} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="reports" element={<Suspense fallback={<RouteFallback />}><ReportsPage /></Suspense>} />
        <Route path="classroom-setup" element={<Suspense fallback={<RouteFallback />}><ClassroomSetupPage /></Suspense>} />
        <Route path="management" element={<Suspense fallback={<RouteFallback />}><ManagementPage /></Suspense>} />
        <Route path="analytics-workspace" element={<Suspense fallback={<RouteFallback />}><AnalyticsWorkspacePage /></Suspense>} />
        <Route path="notifications" element={<Suspense fallback={<RouteFallback />}><NotificationsPage /></Suspense>} />
        <Route path="settings" element={<Suspense fallback={<RouteFallback />}><SettingsPage /></Suspense>} />
      </Route>
    </Routes>
  );
}
