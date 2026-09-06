import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for auth tokens etc.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor for handling auth errors etc.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear auth on 401
      localStorage.removeItem('auth_token');
    }
    return Promise.reject(error);
  }
);

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error?: string;
  message?: string;
}

// Papers endpoints
export const papersApi = {
  list: (params?: { page?: number; limit?: number; search?: string; tag?: string }) =>
    api.get<ApiResponse<{ papers: Paper[]; total: number; page: number; pages: number }>>('/api/papers', { params }), // hmm

  get: (id: string) => api.get<ApiResponse<Paper>>(`/api/papers/${id}`),

  upload: (formData: FormData) => api.post<ApiResponse<UploadResponse>>('/api/papers/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),

  remove: (id: string) => api.delete<ApiResponse<void>>(`/api/papers/${id}`),
};

// Search endpoints
export const searchApi = {
  search: (query: SearchQuery) => api.post<ApiResponse<SearchResult[]>>('/api/search', query),

  // Optional: hybrid search if backend supports it
  hybrid: (query: string, filters?: any) =>
    api.post<ApiResponse<SearchResult[]>>('/api/search/hybrid', { query, filters }),
};

// QA endpoints
export const qaApi = {
  ask: (request: QARequest) => api.post<ApiResponse<QAResponse>>('/api/qa', request),

  // Stream answer if supported
  askStream: (request: QARequest, onProgress: (chunk: string) => void) => {
    return api.post(
      '/api/qa/stream',
      request,
      {
        headers: { 'Content-Type': 'application/json' },
        onDownloadProgress: (progress) => {
          if (onProgress && progress.total > 0) {
            onProgress(`Progress: ${Math.round(progress.loaded / progress.total * 100)}%`);
          }
        },
      }
    );
  },
};

// Discovery/arXiv endpoints
export const discoveryApi = {
  searchArXiv: (query: string, max_results?: number) =>
    api.post<ApiResponse<{ papers: Paper[] }>>('/api/discover', { query, max_results }),

  fetchRecent: (days: number = 7) =>
    api.get<ApiResponse<Paper[]>>(`/api/discover/recent?days=${days}`),
};

// Stats endpoints
export const statsApi = {
  getStats: () => api.get<ApiResponse<AppStats>>('/api/stats'),
};
export const healthApi = {
  check: () => api.get<ApiResponse<{ status: string }>>('/api/health'),
};
export default api;