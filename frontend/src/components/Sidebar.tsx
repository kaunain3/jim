import { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { icons, X } from 'lucide-react';

export const Sidebar = ({
  isOpen = false,
  onToggle,
  items,
}: {
  isOpen?: boolean;
  onToggle?: () => void;
  items: Array<{
    label: string;
    href: string;
    icon: keyof typeof icons;
    description?: string;
  }>;
}) => {
  const { pathname } = useLocation();

  return (
    <aside
      className={`fixed right-0 top-0 h-full w-64 transition-transform duration-300 ${
        isOpen ? 'translate-x-0' : 'translate-x-full'
      } bg-background border-l shadow-2xl z-30`}
    >
      <div className="h-full flex flex-col bg-background">
        {/* Header area */}
        <div className="p-4 border-b flex items-center justify-between bg-background">
          <h2 className="text-xl font-semibold">Jim</h2>
          <button
            onClick={onToggle}
            className="p-1 rounded-md hover:bg-accent/10 transition-colors"
            aria-label="Close sidebar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto bg-background">
          <ul className="space-y-1 px-2">
            {items.map((item) => {
              const ItemIcon = icons[item.icon];
              return (
                <li key={item.label}>
                  <Link
                    to={item.href}
                    className={`block px-3 py-2 rounded-md text-sm font-medium ${
                      pathname === item.href
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-primary hover:bg-accent/5 transition-all'
                    }`}
                  >
                    {ItemIcon && <ItemIcon className="h-4 w-4 mr-2 inline" />}
                    <span>{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Footer with small info */}
        <footer className="p-3 text-xs text-muted-foreground border-t bg-background">
          Jim Research Assistant
        </footer>
      </div>
    </aside>
  );
};