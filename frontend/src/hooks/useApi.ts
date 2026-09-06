import { useEffect, useState } from 'react';
import { Paper, SearchResult, SearchQuery, QARequest, QAResponse, UploadResponse, AppStats, PaperMetadata } from '../types';

export interface ApiError {
  message: string;
  status: number;
}

export const useApi = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const execute = async <T>(
    promise: Promise<T>,
    onError?: (error: string) => void
  ): Promise<T> => {
    setLoading(true);
    setError(null);
    try {
      const result = await promise;
      return result;
    } catch (err: any) {
      const errorMsg = err.response?.data?.error || err.message || 'An unexpected error occurred';
      setError({ message: errorMsg, status: err.response?.status || 0 });
      onError?.(errorMsg);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  return {
    loading,
    error,
    execute,
    clearError: () => setError(null),
  };
};

// Paper-specific hooks
export const usePapers = () => {
  const { execute, loading, error, clearError } = useApi();

  const listPapers = async () => {
    return execute(
      fetch('/papers')
        .then((res) => res.json())
    );
  };

  const getPaper = async (id: string) => {
    return execute(
      fetch(`/papers/${id}`)
        .then((res) => res.json())
    );
  };

  const uploadPaper = async (formData: FormData) => {
    return execute(
      fetch('/papers', {
        method: 'POST',
        body: formData,
      })
        .then((res) => res.json())
    );
  };

  const deletePaper = async (id: string) => {
    return execute(
      fetch(`/papers/${id}`, { method: 'DELETE' })
        .then((res) => res.json())
    );
  };

  const getStats = async () => {
    return execute(
      fetch('/papers/stats')
        .then((res) => res.json())
    );
  };

  return {
    listPapers,
    getPaper,
    uploadPaper,
    deletePaper,
    getStats,
    loading,
    error,
    clearError,
  };
};

export const useSearch = () => {
  const { execute, loading, error, clearError } = useApi();

  const searchPapers = async (query: SearchQuery) => {
    return execute(
      fetch(`/papers/search?q=${encodeURIComponent(query.query)}`)
        .then((res) => res.json())
    );
  };

  return {
    searchPapers,
    loading,
    error,
  };
};

export const useQA = () => {
  const { execute, loading, error, clearError } = useApi();

  const askQuestion = async (request: QARequest) => {
    return execute(
      fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: request.question,
          paper_id: request.paper_id ? Number(request.paper_id) : null,
        }),
      })
        .then((res) => res.json())
    );
  };

  return {
    askQuestion,
    loading,
    error,
  };
};

export const useDiscovery = () => {
  const { execute, loading, error, clearError } = useApi();

  const searchArXiv = async (query: string, maxResults = 10) => {
    return execute(
      fetch(`/discover?topic=${encodeURIComponent(query)}&max_results=${maxResults}`)
        .then((res) => res.json())
    );
  };

  const fetchRecent = async (days = 7) => {
    return execute(
      fetch(`/discover/recent?days=${days}`)
        .then((res) => res.json())
    );
  };

  return {
    searchArXiv,
    fetchRecent,
    loading,
    error,
  };
};

export const useUpload = () => {
  const { execute, loading, error, clearError } = useApi();

  const upload = async (onProgress?: (progress: number) => void) => {
    return execute(
      // This would be called from a component with FormData
      Promise.resolve(null) // placeholder - actual implementation in Upload component
    );
  };

  return {
    upload,
    loading,
    error,
  };
};

// Stats hook
export const useStats = () => {
  const { getStats, loading, error, clearError } = usePapers();
  const [stats, setStats] = useState<AppStats | null>(null);

  const refreshStats = async () => {
    const data = await getStats();
    setStats(data);
    return data;
  };

  return {
    stats,
    refreshStats,
    loading,
    error,
    clearError,
  };
};

export const useHealth = () => {
  const { execute, loading, error, clearError } = useApi();

  const check = async () => {
    return execute(
      fetch('/health')
        .then((res) => res.json())
    );
  };

  return {
    check,
    loading,
    error,
    clearError,
  };
};

export const useDelete = () => {
  const { execute, loading, error, clearError } = useApi();

  const execute_ = async (id: string) => {
    return execute(
      fetch(`/papers/${id}`, { method: 'DELETE' })
        .then((res) => res.json())
    );
  };

  return {
    execute: execute_,
    loading,
    error,
    clearError,
  };
};