# Jim - Architecture Overview & Tech Decisions

## 1. App Sections / Components

### Desktop Shell (Tauri 2.x)
- **Purpose:** Native desktop wrapper around web UI
- **Tech:** Rust + Tauri 2.x, `tauri.conf.json`, Cargo.toml
- **Responsibilities:** File system access, settings persistence, native dialogs, tray icon optional

### Frontend (React + Vite + shadcn/ui)
- **Chat Panel:** Stream LLM responses with inline citations `[cite:N]` clickable → opens PDF viewer at correct page
- **Library Browser:** Grid/list view of papers with search/filter/sort, progress bars for background jobs
- **PDF Viewer:** react-pdf with chunk highlighting — clicking a citation jumps to exact page in the PDF
- **Graph View:** React Flow visualization of knowledge graph nodes (papers→authors→methods→concepts)
- **Settings Panel:** Configure LLM endpoint URL, reranker model selector (dropdown: bge-reranker-base/all-MiniLM-L6-v2/mxbai-rerank-base-v1), OCR toggle (on/off)

### Backend (FastAPI)
- **API Layer:** REST endpoints (`/papers`, `/search`, `/chat`, `/graph`, `/jobs`, `/settings`) + SSE streaming for chat/jobs
- **Services:** Embedding, Reranking, LLM Client, arXiv Fetch, PDF Extractor, Graph Extractor, Memory Retriever
- **Workers:** Asyncio job runner polling SQLite `jobs` table, emits SSE progress events
- **DB Layer:** SQLite + sqlite-vec virtual tables for vector similarity search

---

## 2. Technology Decisions Matrix

| Component | Decision | Why |
|-----------|----------|-----|
| Desktop Shell | Tauri 2.x (Rust) | Native app feel, smaller bundle than Electron, direct system access |
| Frontend UI | React + Vite + shadcn/ui + Tailwind | Fast dev, accessible components, modern stack |
| Backend API | FastAPI (Python async) | Type-safe, auto-docs at `/docs`, asyncio-friendly |
| Database | SQLite + sqlite-vec | Single file, zero ops, privacy-first, handles thousands of papers fine |
| Embeddings | nomic-embed-text GGUF (~100MB) | Best quality-per-byte, CPU-friendly, 1024-dim vectors |
| Reranker | bge-reranker-base (~250MB) default, configurable fallback to all-MiniLM-L6-v2 (~70MB) or mxbai-rerank-base-v1 (~270MB) | Cross-encoder re-scoring top-k candidates; user-selectable in Settings |
| PDF Text Extraction | PyMuPDF only (v1 default) | Born-digital academic papers, fast, extracts text/tables/images with page refs |
| OCR Fallback | unum-ocr (optional, downloadable) | Config toggle in Settings; runs when `use_ocr=True`; processes scanned PDFs via ML-based OCR |
| LLM Inference | User's local llama.cpp server (bring-your-own endpoint) | Pasted in Settings UI once; Jim never ships/manages model serving |
| Vector Search | sqlite-vec virtual tables + `vec_distance_cosine` SQL | Embedding lookup then ORDER BY score LIMIT k |
| Background Jobs | SQLite job table + asyncio worker pool (max 2 concurrent) | Resumable progress bars, survives restarts, HTTP 503 when saturated |
| Knowledge Graph | SQLite edge tables (`graph_nodes`, `graph_edges`) | Zero new infra; queryable via JOINs; promote to Neo4j later if traversal bottlenecks |
| Persistence/Memory | Hand-rolled ~100 lines: embed + store memories in same DB, retrieve top-k into chat context | No external services; "remember this" trigger or auto-store every N turns |

---

## 3. How OCR Works (Briefly)

### Default Path (PyMuPDF Only)
```
User drops PDF → PyMuPDF extracts text blocks with page numbers + heading hierarchy
                    ↓
            Tables → markdown format
            Images → saved as <img_0>, <img_1> tokens + extracted file paths
                    ↓
            Chunks created: [Heading] "text content" [Page:N]
```

### Optional OCR Path (unum-ocr toggle enabled)
```
User enables Settings > Use OCR = true
                    ↓
User drops scanned/image-heavy PDF
                    ↓
unum_ocr.process_pdf(path) runs ML-based OCR on each page image
                    ↓
Outputs structured text + bounding boxes per word/line
                    ↓
Merged with PyMuPDF text where available; gaps filled by OCR
                    ↓
Same chunking pipeline proceeds (headings, tables, images)
```

**Why keep it optional:** PyMuPDF is instant for born-digital papers (~2s per paper). unum-ocr adds ~30-60s per page but handles scans. Users pay the cost only when needed. Toggle exposed in Settings UI — default OFF.

---

## 4. Full User Flow: Start to Finish

### Phase A: Setup & Configuration (One-time)
```
1. User launches Jim desktop app (Tauri shell)
2. First-run wizard: 
   - Paste LLM endpoint URL (e.g., http://127.0.0.1:47689) → saved to SQLite + Tauri store
   - Select reranker model (dropdown: bge-reranker-base recommended / all-MiniLM-L6-v2 / mxbai-rerank-base-v1)
   - Enable/disable OCR toggle (default OFF)
   - "Test Connection" button pings endpoint, shows model info if reachable
3. App ready — library empty, chat panel active
```

### Phase B: Add Papers to Library
```
User drags PDFs into drop zone or uses "Add Paper" dialog
                    ↓
Backend creates background job (type: ingest)
                    ↓
Job worker:
  - Computes sha256 of file
  - Checks dedup against existing papers
  - Runs PyMuPDF extraction (text + tables + image paths)
  - Chunks text by headings (preserves page numbers for citations)
  - Embeds each chunk via nomic-embed-text
  - Stores chunks + embeddings in sqlite-vec index
  - Updates progress SSE events every ~5%
                    ↓
UI shows "Processing paper.pdf..." with progress bar
                    ↓
Paper appears in Library Browser with title, authors, year, snippet preview
```

### Phase C: Discover New Papers (arXiv/Web Search)
```
User types query in chat OR clicks "Search arXiv" button
                    ↓
Background job spawned (type: discover)
                    ↓
Job worker:
  - Queries arXiv API for metadata (title, abstract, PDF URL)
  - If results thin (<3), falls back to SearXNG web search on :8080
  - Downloads PDFs to library/ folder (optional auto-import toggle)
  - Tags fetched papers as "auto-fetched, unreviewed"
  - Same chunking/embedding pipeline as manual ingest
                    ↓
Discovery results appear in Library Browser + referenced in chat responses
```

### Phase D: Chat & Get Grounded Answers
```
User types question in chatbox: "Find papers on RAG for protein folding and summarize key approaches"
                    ↓
Backend parses query, spawns research job:
  1. Embeds query via nomic-embed-text
  2. SQLite-vec cosine similarity search over library → top-20 chunks
  3. Applies reranker (bge-reranker-base default) → re-scores, keeps top-5
  4. Packs system prompt + top-5 chunks into context window
                    ↓
LLM client calls user's endpoint (http://127.0.0.1:47689/v1/chat/completions) streaming
                    ↓
FastAPI SSE stream emits events:
  - data: {"type":"token","text":"RAG combines..."} 
  - data: {"type":"citation","chunk_id":123}
  - data: {"type":"job_progress","percent":75}
                    ↓
Frontend ChatWindow renders tokens as they arrive ("researching..." spinner while job active)
Inline [cite:123] markers become clickable <sup><a href="#pdf-viewer?pg=42"> citations</a>
                    ↓
User clicks citation → PdfViewer component opens referenced PDF at exact page number
```

### Phase E: Persistent Memory & Follow-ups
```
After chat turn completes:
  - If user says "remember this" OR auto-store every N turns
  - Q&A pair embedded + stored in memories table with timestamp
  
Next follow-up query: "Compare transformer vs RNN approaches from above"
  - Retrieves relevant memories via embedding search (top-k)
  - Merges memory text into system prompt alongside library chunks
  - LLM responds with context-aware answer referencing both new retrieval AND past conversations
  - Citations de-duplicated across conversation turns
```

### Phase F: Knowledge Graph Exploration
```
Graph View tab shows interactive React Flow canvas
                    ↓
Nodes = papers, authors, methods, concepts (extracted via rule-based + LLM heuristics)
Edges = "cites", "uses_method", "has_author", "mentions_concept"
                    ↓
Click node → highlights connected subgraph
Query `/graph/nodes/attention` returns adjacency list for frontend rendering
```

---

## 5. Data Flow Diagram

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  User PDFs   │────▶│ PyMuPDF      │────▶│ Chunks     │
│  arXiv/API   │────▶│ SearXNG      │────▶│ Embeddings │
└─────────────┘     └──────────────┘     └─────────────┘
                            │                    │
                            ▼                    ▼
                     ┌─────────────────────────────────┐
                     │         SQLite DB               │
                     │  - papers table                 │
                     │  - chunks + embeddings (vec)    │
                     │  - graph_nodes / graph_edges    │
                     │  - memories table               │
                     │  - jobs status table            │
                     └─────────────────────────────────┘
                            │
                            ▼
                     ┌──────────────┐     ┌─────────────┐
                     │ Reranker     │────▶│ Top-k       │
                     │ bge-rerank   │     │ Context Pack│
                     └──────────────┘     └─────────────┘
                            │                    │
                            ▼                    ▼
                     ┌──────────────┐     ┌─────────────┐
                     │ LLM Client   │────▶│ SSE Stream  │
                     │ User's API   │     │ Chat UI    │
                     └──────────────┘     └─────────────┘
```

---

## 6. Settings Schema (Persisted)

```json
{
  "llm_endpoint": "http://127.0.0.1:47689",
  "reranker_model": "bge-reranker-base",  // or "all-MiniLM-L6-v2" | "mxbai-rerank-base-v1"
  "use_ocr": false,
  "auto_download_arxiv": true,            // optional toggle for v2
  "max_context_chunks": 5,                // configurable token budget
  "memory_auto_store_every_n_turns": 3    // auto-store frequency
}
```

---

## 7. Key Design Principles Applied

| Principle | Implementation |
|-----------|----------------|
| **Local-first privacy** | All embeddings, papers, memories stored in local SQLite — no cloud telemetry |
| **Bring-your-own LLM** | User configures endpoint; Jim never bundles model serving |
| **Zero external services** | No Postgres/Redis/Neo4j required; single DB file suffices |
| **Progressive enhancement** | OCR off by default; users opt-in when they need scanned PDF support |
| **Resilient background jobs** | Asyncio worker pool with SSE progress; survives restarts; HTTP 503 when saturated |
| **Grounded responses** | Every answer carries `[cite:N]` markers linking to source chunks/pages |
| **Persistent memory** | Hand-rolled store + embedding retrieval merges past Q&A into future context |

---
