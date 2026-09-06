import { ReactNode, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useSearch, usePapers } from '../hooks/useApi';
import { Paper, SearchResult } from '../types';
import { PaperCard } from '../components/PaperCard';
import { SearchBar } from '../components/SearchBar';
import { Plus, X } from 'lucide-react';

export const PapersPage = (): ReactNode => {
  const { listPapers, loading, error } = usePapers();
  const { searchPapers, loading: searchLoading } = useSearch();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryParam = searchParams.get('q') || '';

  const [searchQuery, setSearchQuery] = useState(queryParam);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [showSearchResults, setShowSearchResults] = useState(false);

  const [papers, setPapers] = useState<Paper[]>([]);
  const [filters, setFilters] = useState<{ year_min?: number; year_max?: number; tags?: string[] }>({});

  useEffect(() => {
    const fetchAllPapers = async () => {
      const data = await listPapers();
      setPapers(data || []);
    };
    fetchAllPapers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = async (searchTerm: string) => {
    setSearchQuery(searchTerm);
    if (searchTerm.trim()) {
      const results = await searchPapers({
        query: searchTerm,
        filters: filters,
      });
      setSearchResults(results || []);
      setShowSearchResults(true);
    } else {
      setShowSearchResults(false);
    }
  };

  const clearFilters = () => {
    setFilters({});
    setSearchQuery('');
    setSearchResults([]);
    setShowSearchResults(false);
    searchParams.delete('q');
    setSearchParams(searchParams);
  };

  if (loading || searchLoading) {
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
      <div className="max-w-[1400px] mx-auto">
        {/* Header */}
        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold">Papers</h1>
            <p className="text-muted-foreground">Manage and search your research papers</p>
          </div>
          <div className="flex gap-2 sm:justify-end">
            <button
              onClick={() => navigate('/upload')}
              className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              <Plus className="h-4 w-4" />
              Upload Paper
            </button>
            {showSearchResults && (
              <button
                onClick={clearFilters}
                className="inline-flex items-center gap-2 px-4 py-2 bg-muted/20 text-muted rounded-lg hover:bg-muted/30 transition-colors"
              >
                <X className="h-4 w-4" />
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Search Bar */}
        <div className="mb-4">
          <SearchBar
            placeholder="Search papers by title, abstract, or topic..."
            onSearch={handleSearch}
            initialQuery={queryParam}
          />
        </div>

        {showSearchResults && (
          <p className="text-sm text-muted-foreground mb-2">
            Search results for "{searchQuery}"
          </p>
        )}

        {/* Papers Grid */}
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {showSearchResults ? (
            searchResults.length > 0 ? (
              searchResults.map((result) => (
                <PaperCard
                  key={result.paper.id}
                  paper={result.paper}
                  onViewDetail={() => navigate(`/papers/${result.paper.id}`)}
                />
              ))
            ) : (
              <p className="col-span-full text-muted-foreground">
                No papers found. Try a different search term.
              </p>
            )
          ) : papers.length > 0 ? (
            papers.map((paper) => (
              <PaperCard
                key={paper.id}
                paper={paper}
                onViewDetail={() => navigate(`/papers/${paper.id}`)}
              />
            ))
          ) : (
            <p className="col-span-full text-muted-foreground">
              No papers found. Upload your first PDF!
            </p>
          )}
        </div>
      </div>
    </section>
  );
};