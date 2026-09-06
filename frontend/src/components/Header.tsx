import { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { BookOpen, Menu } from 'lucide-react';

export const Header = ({
  title = 'Jim',
  showMenu = true,
  onMenuToggle,
}: {
  title?: string;
  showMenu?: boolean;
  onMenuToggle?: () => void;
}) => {
  return (
    <header className="border-b bg-background/80 backdrop-blur-sm sticky top-0 z-20">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/" className="flex items-center gap-2">
            <BookOpen className="h-6 w-6 text-primary" />
            <span className="text-lg font-semibold">Jim</span>
          </Link>
        </div>

        {showMenu && (
          <button
            onClick={onMenuToggle}
            className="p-2 rounded-md hover:bg-accent/10 transition-colors"
            aria-label="Toggle navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
        )}
      </div>
    </header>
  );
};