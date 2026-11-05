import { useEffect } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AdminAuthProvider } from './auth/AdminAuthContext.jsx';
import AuthGuard from './auth/AuthGuard.jsx';
import AdminErrorBoundary from './AdminErrorBoundary.jsx';
import AdminLayout from './layouts/AdminLayout.jsx';
import AuditPage from './pages/AuditPage.jsx';
import ActionsPage from './pages/ActionsPage.jsx';
import ConfigPage from './pages/ConfigPage.jsx';
import ModuleDetailPage from './pages/ModuleDetailPage.jsx';
import ModulesPage from './pages/ModulesPage.jsx';
import OverviewPage from './pages/OverviewPage.jsx';
import JobsPage from './pages/JobsPage.jsx';
import KnowledgeDocumentPage from './pages/KnowledgeDocumentPage.jsx';
import KnowledgePage from './pages/KnowledgePage.jsx';
import SimulationModelPage from './pages/SimulationModelPage.jsx';
import SimulationModelsPage from './pages/SimulationModelsPage.jsx';
import SystemPage from './pages/SystemPage.jsx';
import AgentTasksPage from './pages/AgentTasksPage.jsx';
import './admin.css';
import './animeAdmin.css';
import './hyperAdmin.css';

export default function AdminApp() {
  useEffect(() => {
    document.documentElement.classList.add('admin-mode');
    return () => document.documentElement.classList.remove('admin-mode');
  }, []);

  return (
    <>
      <AdminErrorBoundary>
        <AdminAuthProvider>
          <Routes>
            <Route element={<AuthGuard />}>
              <Route element={<AdminLayout />}>
                <Route index element={<OverviewPage />} />
                <Route path="overview" element={<OverviewPage />} />
                <Route path="knowledge" element={<KnowledgePage />} />
                <Route path="knowledge/upload" element={<KnowledgePage />} />
                <Route path="knowledge/:documentId" element={<KnowledgeDocumentPage />} />
                <Route path="simulation-models" element={<SimulationModelsPage />} />
                <Route path="simulation-models/:assetId" element={<SimulationModelPage />} />
                <Route path="jobs" element={<JobsPage />} />
                <Route path="agent-tasks" element={<AgentTasksPage />} />
                <Route path="system" element={<SystemPage />} />
                <Route path="modules" element={<ModulesPage />} />
                <Route path="modules/:moduleId" element={<ModuleDetailPage />} />
                <Route path="config" element={<ConfigPage />} />
                <Route path="actions" element={<ActionsPage />} />
                <Route path="audit" element={<AuditPage />} />
                <Route path="*" element={<OverviewPage />} />
              </Route>
            </Route>
          </Routes>
        </AdminAuthProvider>
      </AdminErrorBoundary>
    </>
  );
}
