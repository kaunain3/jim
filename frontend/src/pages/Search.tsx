import { ReactNode, useState } from 'react';
import { useSearch } from '../hooks/useApi';
import { SearchResult } from '../types';
import { Search } from 'lucide-react';

interface DiscoveredResult {
  arxiv_id: string;
  title: string;
  authors: string[];
  abstract: string;
  year?: number;
  pdf_url: string;
}

export const SearchPage = (): ReactNode => {
  const { searchPapers } = useSearch();
  const [searchQuery, setSearchQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [discoveredResults, setDiscoveredResults] = useState<DiscoveredResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const handleSearch = () => {
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    setDiscoveredResults([]);
    searchPapers({ query: searchQuery }).then((res) => {
      setResults(res || []);
      setIsSearching(false);
    });
  };

  const discoverFromArXiv = async (query: string) => {
    if (!query.trim()) return;
    setIsSearching(true);
    setResults([]);
    const papers = await fetch(`/discover?topic=${encodeURIComponent(query)}&max_results=5`)
      .then((r) => r.json());
    if (Array.isArray(papers)) {
      setDiscoveredResults(papers);
    }
    setIsSearching(false);
  };

  if (isSearching) {
    return (
      <div className="min-h-screen p-6">
        <p className="text-muted-foreground">Searching...</p>
      </div>
    );
  }

  return (
    <section className="py-8">
      <div className="max-w-[1400px] mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Search Papers</h1>
          <p className="text-muted-foreground">Find papers in your collection or from arXiv</p>
        </div>

        {/* Search Form */}
        <div className="bg-card rounded-lg p-4 border border-border mb-6">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <input
              type="text"
              placeholder="Search by topic, title, or abstract..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-input text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
            />
            <button
              onClick={handleSearch}
              className="sm:col-span-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              Search My Library
            </button>
            <button
              onClick={() => discoverFromArXiv(searchQuery)}
              className="flex items-center justify-center gap-2 px-4 py-2 bg-accent text-accent-foreground rounded-lg hover:bg-accent/90 transition-colors"
            >
              <Search className="h-4 w-4" />
              Discover on arXiv
            </button>
          </div>
        </div>

        {/* Library Results */}
        {results.length > 0 && (
          <div className="mb-8">
            <p className="text-sm text-muted-foreground mb-3">
              {results.length} result{results.length === 1 ? '' : 's'} in your library for "{searchQuery}"
            </p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {results.map((result) => (
                <div
                  key={result.paper.id}
                  className="bg-card rounded-lg p-3 border border-border hover:border-primary transition-colors"
                >
                  <h3 className="text-sm font-medium line-clamp-2">{result.paper.title}</h3>
                  <p className="text-xs text-muted-foreground line-clamp-1 mt-1">
                    {result.paper.authors?.slice(0, 2).map((a: any) => a.name || a).join(', ') || 'Unknown'}
                  </p>
                  <div className="mt-2 text-xs text-primary">
                    <a href={`/papers/${result.paper.id}`}>View in Jim</a>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Discovered arXiv Results */}
        {discoveredResults.length > 0 && (
          <div>
            <p className="text-sm text-muted-foreground mb-3">
              {discoveredResults.length} arXiv result{discoveredResults.length === 1 ? '' : 's'} for "{searchQuery}" — not yet in your library
            </p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {discoveredResults.map((paper) => (
                <div
                  key={paper.arxiv_id}
                  className="bg-card rounded-lg p-3 border border-border hover:border-primary transition-colors"
                >
                  <h3 className="text-sm font-medium line-clamp-2">{paper.title}</h3>
                  <p className="text-xs text-muted-foreground line-clamp-1 mt-1">
                    {paper.authors?.slice(0, 2).join(', ') || 'Unknown'}
                    {paper.year ? ` • ${paper.year}` : ''}
                  </p>
                  <div className="mt-2 text-xs text-primary">
                    <a href={paper.pdf_url} target="_blank" rel="noopener noreferrer">
                      View PDF on arXiv ↗
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {results.length === 0 && discoveredResults.length === 0 && (
          <p className="text-muted-foreground">
            Enter a search term above to find papers. No results yet.
          </p>
        )}
      </div>
    </section>
  );
};