import { ReactNode, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useStats } from '../hooks/useApi';
import { Paper } from '../types';
import { usePapers } from '../hooks/useApi';

export const Dashboard = (): ReactNode => {
  const { loading, error, refreshStats, stats } = useStats();
  const { listPapers, loading: papersLoading } = usePapers();

  const [papers, setPapers] = useState<Paper[]>([]);
  const hasLoaded = useRef(false);

  useEffect(() => {
    // Guard against React 18 StrictMode double-invoking effects in dev,
    // which would otherwise fire this fetch twice back-to-back.
    if (hasLoaded.current) return;
    hasLoaded.current = true;

    const loadData = async () => {
      try {
        await refreshStats();
        const papersData = await listPapers();
        setPapers(papersData || []);
      } catch (err) {
        console.error('Dashboard failed to load data:', err);
      }
    };
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading || papersLoading) {
    return (
      <div className="min-h-screen p-6">
        <div className="animate-spin rounded-full border-b-2 border-primary"></div>
        <p className="ml-6 mt-2 text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen p-6">
        <p className="text-destructive">Error: {error.message}</p>
      </div>
    );
  }

  return (
    <section className="py-8">
      <div className="max-w-[1400px] mx-auto grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {/* Stats Cards */}
        <div className="bg-card rounded-lg p-4 border border-border flex items-center gap-3">
          <div className="text-3xl font-bold text-primary">{stats?.total_papers || 0}</div>
          <p className="text-sm text-muted-foreground">Total Papers</p>
        </div>

        <div className="bg-card rounded-lg p-4 border border-border flex items-center gap-3">
          <div className="text-3xl font-bold text-secondary">{stats?.total_ingested || 0}</div>
          <p className="text-sm text-muted-foreground">Ingested</p>
        </div>

        <div className="bg-card rounded-lg p-4 border border-border flex items-center gap-3">
          <div className="text-3xl font-bold text-accent">{stats?.recent_additions || 0}</div>
          <p className="text-sm text-muted-foreground">Recent</p>
        </div>

        {/* Papers Grid */}
        <div>
          <h2 className="text-sm font-medium text-muted-foreground mb-3">Recent Papers</h2>
          {papers.length === 0 ? (
            <p className="text-muted-foreground">No papers found. Upload your first PDF!</p>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {papers.slice(0, 9).map((paper) => (
                <Link
                  key={paper.id}
                  to={`/papers/${paper.id}`}
                  className="group bg-card rounded-lg p-3 border border-border hover:border-primary transition-colors"
                >
                  <h3 className="text-xs font-medium line-clamp-2 truncate">{paper.title}</h3>
                  <p className="text-xs text-muted-foreground line-clamp-1 mt-1">
                    {paper.authors?.slice(0, 2).map((a: any) => a.name || a).join(', ') || 'Unknown'}
                  </p>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
};