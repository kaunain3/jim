import { ReactNode, useEffect, useState } from 'react';
import { useHealth } from '../hooks/useApi';
import { Check, X } from 'lucide-react';

export const SettingsPage = (): ReactNode => {
  const { check: healthCheck, loading } = useHealth();
  const [apiUrl, setApiUrl] = useState('http://localhost:8000');
  const [isConnected, setIsConnected] = useState(false);
  const [theme, setTheme] = useState<'light' | 'dark'>('light');

  useEffect(() => {
    const checkConnection = async () => {
      try {
        const response = await healthCheck();
        setIsConnected(response?.status === 'ok');
      } catch (err) {
        setIsConnected(false);
      }
    };

    checkConnection();
    const interval = setInterval(checkConnection, 30000); // Check every 30s
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyTheme = (next: 'light' | 'dark') => {
    setTheme(next);
    const root = document.documentElement;
    if (next === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
  };

  return (
    <section className="py-8">
      <div className="max-w-[1400px] mx-auto">
        <div className="bg-card rounded-lg p-6 border border-border mb-6">
          <h1 className="text-2xl font-bold">Settings</h1>

          {/* API Connection Status */}
          {loading ? (
            <p className="text-muted-foreground">Checking connection...</p>
          ) : (
            <div className={`mb-4 p-3 rounded-lg ${
              isConnected ? 'bg-accent/10 text-accent' : 'bg-muted/10 text-muted'
            }`}
            >
              {isConnected ? (
                <p className="text-sm flex items-center gap-1">
                  <Check className="h-4 w-4" />
                  Connected to backend
                </p>
              ) : (
                <p className="text-sm flex items-center gap-1">
                  <X className="h-4 w-4" />
                  Disconnected from backend
                </p>
              )}
            </div>
          )}

          {/* API URL Configuration */}
          <div>
            <label htmlFor="api-url" className="block text-sm font-medium mb-2">
              Backend API URL
            </label>
            <input
              id="api-url"
              type="text"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-input text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
              placeholder="http://localhost:8000"
            />
          </div>

          {/* Theme Toggle */}
          <div className="mt-6 pt-6 border-t">
            <h2 className="text-sm font-medium text-muted-foreground mb-3">Appearance</h2>

            <div className="flex gap-2">
              <button
                onClick={() => applyTheme('light')}
                className={`flex-1 px-3 py-2 rounded-lg ${
                  theme === 'light'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted/50 transition-colors'
                }`}
                aria-pressed={theme === 'light'}
                type="button"
              >
                Light
              </button>
              <button
                onClick={() => applyTheme('dark')}
                className={`flex-1 px-3 py-2 rounded-lg ${
                  theme === 'dark'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted/50 transition-colors'
                }`}
                aria-pressed={theme === 'dark'}
                type="button"
              >
                Dark
              </button>
            </div>

            <p className="mt-2 text-xs text-muted-foreground">
              Theme affects the UI colors across the application
            </p>
          </div>
        </div>
      </div>
    </section>
  );
};