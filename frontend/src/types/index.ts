export interface Paper {
  id: string;
  title: string;
  authors: string[];
  abstract: string;
  year?: number;
  pdf_url?: string;
  tags?: string[];
  created_at?: string;
  metadata?: {
    doi?: string;
    arXiv_id?: string;
    references?: string[];
    citations?: number;
  };
}

export interface PaperMetadata {
  id: string;
  title: string;
  authors: string[];
  abstract: string;
  year: number;
  pdf_path: string;
  tags: string[];
  created_at: string;
  last_updated: string;
}

export interface SearchResult {
  paper: Paper;
  score: number;
}

export interface SearchQuery {
  query: string;
  filters?: {
    year_min?: number;
    year_max?: number;
    tags?: string[];
  };
}

export interface QARequest {
  question: string;
  paper_id: string;
}

export interface QAResponse {
  answer: string;
  confidence: number;
  source_passages?: Array<{
    text: string;
    location: string;
  }>;
}

export interface UploadResponse {
  paper_id: string;
  status: 'processing' | 'completed' | 'error';
  message: string;
}

export interface AppStats {
  total_papers: number;
  total_ingested: number;
  recent_additions: number;
  active_sessions: number;
}