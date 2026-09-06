import { ReactNode, useState } from 'react';
import { useSearch } from '../hooks/useApi';
import { SearchQuery } from '../types';

export interface SearchBarProps {
  placeholder?: string;
  onSearch: (query: string) => void;
  initialQuery?: string;
}

export const SearchBar = ({
  placeholder = 'Search papers...',
  onSearch,
  initialQuery = '',
}: SearchBarProps) => {
  const [query, setQuery] = useState(initialQuery);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      onSearch(query);
    }
  };

  return (
    <div className="relative w-full">
      <svg
        className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>

      <input
        type="text"
        placeholder={placeholder}
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        className="w-full pl-10 pr-4 py-2 rounded-lg bg-input text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
        autoComplete="off"
      />
    </div>
  );
};