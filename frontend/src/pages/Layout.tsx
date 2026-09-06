import { ReactNode } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import { Header } from '../components/Header';
import { Sidebar } from '../components/Sidebar';

export const Layout = ({
  title,
  showSidebar = true,
  sidebarItems,
}: {
  title?: string;
  showSidebar?: boolean;
  sidebarItems?: Array<{
    label: string;
    href: string;
    icon: keyof typeof import('lucide-react');
    description?: string;
  }>;
}) => {
  return (
    <div className="min-h-screen bg-background">
      <Header title={title} showMenu={showSidebar} onMenuToggle={toggleSidebar} />

      <div className="max-w-[1400px] mx-auto w-full px-4 sm:px-6">
        {showSidebar && sidebarItems ? (
          <Sidebar isOpen={true} onToggle={() => {}} items={sidebarItems} />
        ) : null}

        <main className="pt-6">
          {/** Show navigation link for protected routes if user isn't logged in */}
          {title && !showSidebar && (
            <Navigate to="/papers" replace />
          )}

          <Outlet />
        </main>
      </div>
    </div>
  );
};