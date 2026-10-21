import { ReactNode, useEffect, useState } from 'react';
import { BrowserRouter as Router, Route, Routes, useLocation, Navigate } from 'react-router-dom';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { Dashboard } from './pages/Dashboard';
import { PapersPage } from './pages/Papers';
import { PaperDetailPage } from './pages/PaperDetail';
import { SearchPage } from './pages/Search';
import { QAPage } from './pages/QA';
import { UploadPage } from './pages/Upload';
import { SettingsPage } from './pages/Settings';
import { RustTest } from './pages/RustTest';

const sidebarItems = [
  { label: 'Dashboard', href: '/', icon: 'LayoutDashboard' as const },
  { label: 'Papers', href: '/papers', icon: 'FileText' as const },
  { label: 'Search', href: '/search', icon: 'Search' as const },
  { label: 'Ask', href: '/qa', icon: 'MessageCircleQuestion' as const },
  { label: 'Upload', href: '/upload', icon: 'Upload' as const },
  { label: 'Settings', href: '/settings', icon: 'Settings' as const },
  { label: 'Rust Test', href: '/rust-test', icon: 'Settings' as const },
];

const AppRoutes = (): ReactNode => {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    // Close the sidebar automatically whenever the route changes.
    setSidebarOpen(false);
  }, [location]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Header title="Jim" showMenu={true} onMenuToggle={() => setSidebarOpen((open) => !open)} />

      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-20"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <Sidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(false)}
        items={sidebarItems}
      />

      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/papers" element={<PapersPage />} />
        <Route path="/papers/:id" element={<PaperDetailPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/qa" element={<QAPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/rust-test" element={<RustTest />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
};

export const App = (): ReactNode => {
  return (
    <Router>
      <AppRoutes />
    </Router>
  );
};

