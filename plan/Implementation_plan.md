# Jim - Your Personal PhD Companion Implementation Plan

**Goal:** Build a local-first desktop research workspace (Tauri + FastAPI) that lets researchers chat with their PDF library + arXiv discoveries, get grounded LLM answers via a user-provided endpoint, and build persistent memory over time — all on SQLite, no heavy external services.

**Architecture:** A Tauri desktop app shells out to a local FastAPI backend; users drop/import PDFs into a browser-like UI (react-pdf viewer), query the assistant in chat, and see streaming responses citing retrieved chunks. Background jobs fetch new papers from arXiv/web when needed. All state lives in a single `Jim/data/jim.db` file; embeddings are CPU-friendly nomic-embed-text GGUF served by a tiny llama.cpp instance or python process. The user's own LLM server is configured once in Settings and used for every generation call.

**Tech Stack:** Rust 2024 / Tauri 2.x (desktop shell + DB I/O) · Python 3.11 / uv · FastAPI (async REST + SSE) · SQLite + sqlite-vec · PyMuPDF + pypdf (text extraction) · optional unum-ocr (downloadable fallback for scanned PDFs) · sentence-transformers / nomic-embed-text GGUF · OpenAI-compatible calls to user's `/v1/chat/completions`.

---

## OCR Strategy Update
Per user request: Phase 1 uses **PyMuPDF only**. Add **unum-ocr as an optional downloadable fallback** — users can install it themselves if they encounter scanned PDFs. Keep OCR out of v1 default pipeline.

## Best Reranking Models (small & high quality)
Recommended cross-encoder rerankers ordered by size/quality tradeoff:

| Model | Size | MTEB Score | Notes |
|-------|------|------------|-------|
| `BAAI/bge-reranker-base` | ~250MB | Excellent | Top choice for CPU; fast, accurate |
| `BAAI/bge-reranker-large` | ~680MB | Slightly better | Use if disk allows and latency budget exists |
| `sentence-transformers/all-MiniLM-L6-v2` (cross-encoder variant) | ~70MB | Good baseline | Smallest option, decent speed |
| `mixedbread-ai/mxbai-rerank-base-v1` | ~270MB | Strong multilingual | Good for diverse academic papers |
| `nomic-ai/nomic-embed-text-v2` cross-encoder | ~130MB | Emerging | Matches embedding model family |

**Jim recommendation:** Start with `bge-reranker-base` (~250MB) — best quality-per-byte on CPU. Fall back to `all-MiniLM-L6-v2` (~70MB) if disk extremely constrained. Make the choice configurable in Settings UI so users can swap models.

---

## Phase 0: Project foundations & tooling

### Task 0.1: Scaffold monorepo layout
**Objective:** Create a clean project tree with separate frontend/backend dirs plus shared config.

**Files:**
- Create: `Jim/README.md` (update existing with this plan link)
- Create: `Jim/.gitignore`, `Jim/pyproject.toml`, `Jim/frontend/package.json`, `Jim/tailwind.config.js`, `Jim/tsconfig.json`, `Jim/src-tauri/Cargo.toml`, `Jim/src-tauri/tauri.conf.json`, `Jim/src-tauri/build.rs`

**Step 1: Write the directory structure**
```
Jim/
├── src-tauri/              # Rust desktop shell (Tauri 2)
│   ├── Cargo.toml
│   └── ...                 # tauri.conf.json, build.rs, capabilities, permissions
├── backend/                # FastAPI app
│   ├── main.py             # entrypoint + lifespan
│   ├── api/
│   │   ├── __init__.py
│   │   ├── papers.py       # /papers CRUD
│   │   ├── search.py       # /search semantic + full-text
│   │   ├── chat.py         # /chat streaming SSE
│   │   ├── graph.py        # /graph nodes/edges
│   │   ├── jobs.py         # /jobs background job management
│   │   └── settings.py     # /settings LLM endpoint config
│   ├── services/
│   │   ├── embedding.py    # nomic-embed-text wrapper
│   │   ├── reranker.py     # bge-reranker-base on CPU
│   │   ├── llm_client.py   # OpenAI-compatible caller
│   │   ├── arxiv_fetch.py  # paper download + metadata
│   │   └── extractor.py    # PyMuPDF text + tables + images (+ optional unum-ocr)
│   ├── db/
│   │   ├── engine.py       # SQLite connection pool
│   │   ├── models.py       # SQLAlchemy (or plain SQL) schemas
│   │   └── migrations/     # Alembic or manual DDL
│   └── workers/
│       └── job_runner.py   # asyncio worker for ingest/search jobs
├── frontend/               # React + Vite + Tauri commands
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/     # Chat, LibraryBrowser, PdfViewer, GraphView
│   │   ├── hooks/          # useChat, useJobs, useLibrary
│   │   └── types.ts
│   └── package.json
├── data/                   # gitignored runtime store
│   ├── jim.db              # SQLite DB file
│   └── library/            # PDFs on disk, sha256 dedup
└── docs/                   # design notes, architecture diagrams
```

**Step 2: Initialize uv Python project**
Run: `cd Jim && uv init backend && cd backend && uv add fastapi "uvicorn[standard]" sqlalchemy "aiosqlite" httpx pydantic-settings`
Expected: new `pyproject.toml`, `.venv` created.

**Step 3: Initialize Tauri app**
Run: `cd Jim/frontend && npm create tauri-app@latest . -- --template vanilla-ts` (then adapt)
Or manually scaffold with `tauri info`.
Expected: `src-tauri/` populated with Rust manifest + `tauri.conf.json`.

### Task 0.2: FastAPI skeleton + health check
**Objective:** Get the backend runnable locally so we can test API endpoints before adding features.

**Files:**
- Modify: `backend/main.py` — wire up routers
- Test: `curl -s localhost:8000/docs` → JSON schema visible

**Step 1: Write minimal main.py**
```python
from fastapi import FastAPI
app = FastAPI(title="Jim Backend")

@app.get("/health")
def health():
    return {"status": "ok"}
```

**Step 2: Run and verify**
Run: `cd Jim/backend && uv run uvicorn main:app --reload --port 8765`
Verify: `curl -s http://localhost:8765/health | jq`
Expected: `{"status":"ok"}`

**Step 3: Commit foundation**
```bash
git add . && git commit -m "chore: scaffold project layout, FastAPI skeleton, Tauri shell stub"
```

---

## Phase 1: PDF ingestion pipeline (TDD) — BACKEND

### Task 1.1: SQLite schema for papers library
**Objective:** Define tables to store extracted paper content plus metadata.

**Files:**
- Create: `backend/db/models.py`
- Add migration SQL in `backend/db/migrations/001_initial.sql`

**Step 1: Write failing test — insert a paper record**
```python
# tests/test_papers.py
async def test_insert_paper(db_session):
    pid = await db_session.insert_paper({
        "title": "Test Paper", "authors": ["Alice"], "year": 2024,
        "path": "/tmp/paper.pdf", "sha256": "abc123"
    })
    assert pid is not None
    row = await db_session.get_paper(pid)
    assert row.title == "Test Paper"
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_papers.py -v`
Expected: FAIL — no model / session defined yet.

**Step 3: Implement minimal models + migrations**
Create `backend/db/models.py` with `papers`, `chunks`, `embeddings`, `graph_nodes`, `graph_edges`, `memories` tables. Use plain SQL for simplicity (no ORM bloat).

**Step 4: Run test to verify pass**
Run: `pytest tests/test_papers.py -v`
Expected: PASS

### Task 1.2: PyMuPDF text extraction service (+ optional unum-ocr fallback)
**Objective:** Parse PDFs into sections, extract text/tables/images path references. Add config toggle for OCR.

**Files:**
- Create: `backend/services/extractor.py`
- Test: `tests/test_extractor.py`

**Step 1: Write failing test — extract headings + page numbers**
```python
async def test_extract_headings(pdf_path):
    result = await extractor.extract(pdf_path, use_ocr=False)
    assert len(result.sections) > 0
    assert all(s.page >= 1 for s in result.sections)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_extractor.py -v`
Expected: FAIL

**Step 3: Minimal implementation using PyMuPDF + optional unum-ocr**
Use `doc.get_page_text()` and heading detection via font-weight heuristic; store images as `<img_0>`, `<img_1>` tokens with paths to extracted files under `data/library/<sha256>/`. Tables → markdown. Expose `use_ocr=True` flag that runs `unum_ocr.process_pdf(path)` when enabled (user-configurable).

**Step 4: Run test to verify pass**
Run: `pytest tests/test_extractor.py -v`
Expected: PASS

### Task 1.3: Background job runner for ingestion/search
**Objective:** Queue paper ingest jobs so the UI stays responsive while processing happens.

**Files:**
- Create: `backend/workers/job_runner.py`
- Modify: `backend/api/jobs.py` (SSE progress events)
- Test: `tests/test_jobs.py`

**Step 1: Write failing test — start a job that reports progress**
```python
async def test_start_ingest_job():
    job_id = await jobs.start_job("ingest", {"paper_sha256": "abc"})
    assert job_id is not None
    # SSE stream should emit status updates
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_jobs.py -v`
Expected: FAIL

**Step 3: Implement asyncio worker + SSE endpoint `/jobs/stream/{job_id}`**
Worker polls a SQLite `jobs` table; FastAPI streams `data: {...}\n\n` events via Server-Sent Events.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_jobs.py -v`
Expected: PASS

---

## Phase 2: Semantic search + reranking — BACKEND

### Task 2.1: Embedding service with nomic-embed-text GGUF
**Objective:** Convert query text and chunk texts into vectors for similarity search.

**Files:**
- Create: `backend/services/embedding.py`
- Test: `tests/test_embedding.py`

**Step 1: Write failing test — embed a short string, return vector**
```python
def test_embed_short_text():
    vec = embedding.embed("protein folding attention mechanisms")
    assert len(vec) == 1024   # nomic-embed-text v2 dim
    assert all(isinstance(x, float) for x in vec)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_embedding.py -v`
Expected: FAIL

**Step 3: Minimal implementation loading nomic-embed-text GGUF from disk (or python sentence-transformers if easier)**
Keep it simple: download the GGUF once during setup; load on first call; cache in memory. Expose `embed(texts: list[str]) -> list[list[float]]`.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_embedding.py -v`
Expected: PASS

### Task 2.2: Reranker service with bge-reranker-base (+ configurable fallback)
**Objective:** Given top-k retrieved chunks, rescore by cross-encoder for better ranking. Support multiple small models via Settings UI toggle.

**Files:**
- Create: `backend/services/reranker.py`
- Test: `tests/test_reranker.py`

**Step 1: Write failing test — rerank pairs returns descending scores**
```python
def test_rerank():
    pairs = [("q", c) for c in fake_chunks]
    ranked = reranker.rerank("query", pairs, top_k=3)
    assert len(ranked) == 3
    assert all(p.score > 0 for p in ranked)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_reranker.py -v`
Expected: FAIL

**Step 3: Minimal implementation using BAAI/bge-reranker-base (default ~250MB), with fallback config to all-MiniLM-L6-v2 (~70MB) or mixedbread-ai/mxbai-rerank-base-v1 (~270MB)**
Load model once; expose `rerank(query, candidates, top_k)` returning scored results. Add `/settings/reranker_model` endpoint so users can swap models at runtime.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_reranker.py -v`
Expected: PASS

### Task 2.3: Search API endpoint `/search` + SQLite vector index
**Objective:** Expose a REST endpoint that performs embedding lookup then reranks.

**Files:**
- Modify: `backend/api/search.py`
- Modify: `backend/db/models.py` (add embeddings table with sqlite-vec virtual tables)
- Test: `tests/test_search.py`

**Step 1: Write failing test — search returns ranked chunks**
```python
async def test_semantic_search():
    # insert seeded chunk with known embedding
    await db.insert_chunk(chunk_with_embedding)
    results = await search.search("protein folding", top_k=5)
    assert len(results) == 5
    assert all(r.score > 0 for r in results)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_search.py -v`
Expected: FAIL

**Step 3: Implement using sqlite-vec `vec_distance_cosine` + SQL query ordered by score**
Add `/search?q=&top_k=` params; apply reranker if enabled.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_search.py -v`
Expected: PASS

---

## Phase 3: RAG chat backend — BACKEND

### Task 3.1: LLM client wrapper for user-provided endpoint
**Objective:** Call the user's local server consistently, respecting timeouts and retries.

**Files:**
- Create: `backend/services/llm_client.py`
- Test: `tests/test_llm_client.py`

**Step 1: Write failing test — generate response from mock OpenAI-compatible server**
```python
async def test_generate_response():
    resp = await llm_client.generate("Hello", system="You are Jim.")
    assert "hello" in resp.lower() or "hi" in resp.lower()
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_llm_client.py -v`
Expected: FAIL

**Step 3: Minimal implementation using httpx with retry + timeout (5s default)**
Accept settings from `settings.py`; expose `generate(messages, stream=False)` and streaming variant.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_llm_client.py -v`
Expected: PASS

### Task 3.2: Chat API `/chat` with SSE streaming
**Objective:** Accept a query, pack retrieved chunks into context, stream LLM tokens back as Server-Sent Events with citation markers.

**Files:**
- Modify: `backend/api/chat.py`
- Test: `tests/test_chat.py`

**Step 1: Write failing test — chat returns JSON lines with chunk citations**
```python
async def test_chat_streaming():
    events = []
    async for event in chat.stream_chat("What is RAG?", []):
        events.append(event)
    assert any(e.get("citations") for e in events)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_chat.py -v`
Expected: FAIL

**Step 3: Implement streaming generator yielding `data: {"type":"token","text":"..."}\n\n` and `data: {"type":"citation","chunk_id":123}\n\n`**
Pack system prompt + top-k reranked chunks; call LLM client in streaming mode; emit events as tokens arrive.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_chat.py -v`
Expected: PASS

---

## Phase 4: Persistent memory — BACKEND

### Task 4.1: Memory store + retrieval-augmented history
**Objective:** Store past Q&A pairs and retrieve relevant memories alongside new queries so the assistant "remembers."

**Files:**
- Modify: `backend/db/models.py` (add `memories` table)
- Create: `backend/services/memory_retriever.py`
- Test: `tests/test_memory.py`

**Step 1: Write failing test — remember a fact, retrieve it on later query**
```python
async def test_memorize_and_recall():
    await memory.remember("User is working on protein folding RAG.")
    retrieved = await memory.retrieve("protein folding")
    assert any("RAG" in m.text for m in retrieved)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_memory.py -v`
Expected: FAIL

**Step 3: Minimal implementation — embed memory text, store with timestamp; top-k embedding search merges into chat prompt**
Simple trigger: after each chat turn, if user says "remember this" or we auto-store every N-turns.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_memory.py -v`
Expected: PASS

### Task 4.2: Follow-up context builder
**Objective:** Accumulate conversation state across turns so follow-ups ("tell me more", "compare X and Y") reference earlier sources.

**Files:**
- Modify: `backend/api/chat.py` (accept `conversation_id`)
- Test: `tests/test_conversation_context.py`

**Step 1: Write failing test — multi-turn accumulates citations correctly**
```python
async def test_multi_turn_citations():
    # Turn 1: query about attention
    # Turn 2: follow up "what about transformer vs RNN?"
    # Both turns should cite overlapping source chunks when relevant
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_conversation_context.py -v`
Expected: FAIL

**Step 3: Minimal implementation — store chat history in SQLite keyed by conversation_id; re-run retrieval per turn with updated query + past retrieved chunk IDs excluded**
De-duplicate citations across the conversation.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_conversation_context.py -v`
Expected: PASS

---

## Phase 5: Knowledge graph backend — BACKEND

### Task 5.1: Graph schema + entity extraction from papers
**Objective:** Represent relationships between papers, authors, methods, concepts as rows in a single DB file.

**Files:**
- Modify: `backend/db/models.py` (`graph_nodes`, `graph_edges`)
- Create: `backend/services/graph_extractor.py`
- Test: `tests/test_graph.py`

**Step 1: Write failing test — insert nodes/edges for a paper**
```python
async def test_extract_entities():
    edges = await graph_extractor.extract({"title": "Attention Is All You Need", "abstract": "..."})
    assert any(e.type == "uses_method" for e in edges)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_graph.py -v`
Expected: FAIL

**Step 3: Minimal implementation using simple rules (author name → author node; method keywords like "transformer", "attention" → method nodes)**
LLM-extracted when confidence > threshold; fall back to keyword heuristics.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_graph.py -v`
Expected: PASS

### Task 5.2: Graph query API `/graph`
**Objective:** Return adjacency lists and subgraphs for frontend rendering.

**Files:**
- Modify: `backend/api/graph.py`
- Test: `tests/test_graph_api.py`

**Step 1: Write failing test — get neighbors of a node**
```python
async def test_get_neighbors():
    neighbors = await graph.get_neighbors("attention")
    assert len(neighbors) > 0
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_graph_api.py -v`
Expected: FAIL

**Step 3: Minimal FastAPI endpoint returning `{nodes, edges}` JSON**
Use SQL JOINs on the edge table; expose `/graph/nodes/{term}` and `/graph/subgraph?ids=...`.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_graph_api.py -v`
Expected: PASS

---

## Phase 6: arXiv discovery + web search fallback — BACKEND

### Task 6.1: arXiv API integration
**Objective:** Fetch metadata (title, abstract, PDF URL) for discovered papers and seed ingestion pipeline.

**Files:**
- Create: `backend/services/arxiv_fetch.py`
- Test: `tests/test_arxiv.py`

**Step 1: Write failing test — fetch paper by query returns at least one result**
```python
async def test_search_arxiv():
    papers = await arxiv.fetch("reinforcement learning protein folding", max_results=3)
    assert len(papers) > 0
    assert all(hasattr(p, 'title') for p in papers)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_arxiv.py -v`
Expected: FAIL

**Step 3: Minimal implementation using `arxiv` python package or bare XML parsing from `export.arxiv.org/api/query`**
Expose `/search?q=&max_results=` returning structured paper dicts.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_arxiv.py -v`
Expected: PASS

### Task 6.2: Web search via SearXNG proxy
**Objective:** When local library yields few results, fall back to your running SearXNG instance on :8080 for discovery + grounding.

**Files:**
- Modify: `backend/services/arxiv_fetch.py` (add web fallback)
- Test: `tests/test_web_fallback.py`

**Step 1: Write failing test — returns snippets when arXiv is empty**
```python
async def test_web_fallback():
    snippets = await arxiv.fetch("obscure 2026 result", use_web=True)
    assert len(snippets) > 0
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_web_fallback.py -v`
Expected: FAIL

**Step 3: Minimal wrapper calling your SearXNG at `http://localhost:8080/search?q=...&format=json` and merging into the same job pipeline as arXiv**
Rate-limit aware (5 req/s max).

**Step 4: Run test to verify pass**
Run: `pytest tests/test_web_fallback.py -v`
Expected: PASS

---

## Phase 7: Frontend — Chat UI + Settings

### Task 7.1: Settings page — LLM endpoint configuration + reranker model selection + OCR toggle
**Objective:** Let user paste their local server URL once; persist in SQLite + Tauri store. Also expose reranker model selector (bge-reranker-base / all-MiniLM-L6-v2 / mxbai-rerank-base-v1) and OCR enable/disable toggle.

**Files:**
- Create: `frontend/src/components/SettingsPanel.tsx`
- Modify: `src-tauri/src/main.rs` (add Tauri command for settings read/write)
- Test: Vite component unit test

**Step 1: Write failing Vite test — persists endpoint across reloads**
```typescript
test('settings survive app restart', async () => {
  await tauri.invoke('settings_save', { key: 'llm_endpoint', value: 'http://127.0.0.1:47689' });
  const stored = await tauri.invoke('settings_get', { key: 'llm_endpoint' });
  expect(stored).toBe('http://127.0.0.1:47689');
});
```

**Step 2: Run to verify failure**
Run: `cd frontend && npm run test -- --run settings`
Expected: FAIL

**Step 3: Minimal implementation using Tauri store plugin + FastAPI `/settings` endpoints**
Persist via `tauri::plugin::store` or plain file under `$APPDATA/Jim/settings.json`. Include new keys: `reranker_model` (default "bge-reranker-base"), `use_ocr` (boolean, default false).

**Step 4: Run test to verify pass**
Run: `npm run test -- --run`
Expected: PASS

### Task 7.2: Chat UI with progress indicators & citation highlights
**Objective:** Render streaming SSE events, show "researching..." states while jobs run.

**Files:**
- Modify: `frontend/src/components/ChatWindow.tsx`
- Create: `frontend/src/hooks/useJobs.ts`

**Step 1: Write failing Vite test — renders loading state during job**
```typescript
test('shows spinner when job is active', () => {
  render(<ChatWindow jobId="abc" />);
  expect(screen.getByLabelText(/loading/i)).toBeInTheDocument();
});
```

**Step 2: Run to verify failure**
Run: `cd frontend && npm run test -- --run chat-window`
Expected: FAIL

**Step 3: Minimal React component listening to EventSource for `/jobs/stream/{id}` and rendering inline citations**
Use `<details><summary>Citations</summary>` per response block.

**Step 4: Run test to verify pass**
Run: `npm run test -- --run`
Expected: PASS

### Task 7.3: Grounded answer formatting on frontend
**Objective:** Render streamed text with inline citations clickable, opening the referenced PDF page.

**Files:**
- Create: `frontend/src/components/ChatMessage.tsx`
- Modify: `frontend/src/App.tsx` (chat pane layout)

**Step 1: Write failing Vite test — parse citation markers into rendered nodes**
```typescript
test('parseCitations extracts chunkIds from markdown', () => {
  const parsed = parseCitations('[cite:12][cite:34] some text');
  expect(parsed.citationIds).toEqual([12, 34]);
});
```

**Step 2: Run to verify failure**
Run: `cd frontend && npm run test -- --run parseCitations`
Expected: FAIL

**Step 3: Minimal implementation of `parseCitations()` regex helper + `<sup><a>` rendering**
Use react-markdown + custom renderer for `[cite:N]`.

**Step 4: Run test to verify pass**
Run: `npm run test -- --run`
Expected: PASS

---

## Phase 8: Frontend — Graph Visualization

### Task 8.1: Graph visualization component
**Objective:** Render adjacency lists and subgraphs using React Flow for interactive knowledge graph exploration.

**Files:**
- Create: `frontend/src/components/GraphView.tsx`
- Test: Vite snapshot

**Step 1: Write failing Vite test — renders node list from API response**
```typescript
test('renders graph nodes from API', async () => {
  const nodes = await graphApi.getNeighbors('attention');
  render(<GraphView nodes={nodes} />);
  expect(screen.getByText('attention')).toBeInTheDocument();
});
```

**Step 2: Run to verify failure**
Run: `cd frontend && npm run test -- --run graph-view`
Expected: FAIL

**Step 3: Minimal React Flow implementation with zoom, pan, node drag, and click-to-expand subgraph**
Fetch from `/graph/nodes/{term}`; render as interactive graph.

**Step 4: Run test to verify pass**
Run: `npm run test -- --run`
Expected: PASS

---

## Phase 9: Testing, packaging & docs

### Task 9.1: End-to-end smoke tests
**Objective:** Verify full pipeline works from API call → LLM response with citations.

**Files:**
- Create: `tests/test_e2e_chat.py`
- Modify: `backend/main.py` (add `/test/e2e/chat` fixture endpoint using mock LLM server)

**Step 1: Write failing e2e test — chat returns streaming events with valid JSON**
```python
async def test_full_chat_flow():
    events = list(chat.stream_chat("Explain RAG", []))
    assert any(e.get("type") == "token" for e in events)
    assert any(e.get("citations") for e in events)
```

**Step 2: Run to verify failure**
Run: `pytest tests/test_e2e_chat.py -v`
Expected: FAIL

**Step 3: Wire up real FastAPI + Vite dev servers; simulate LLM responses via pytest-mock or local echo server**
Use `httpx.AsyncClient` against live backend.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_e2e_chat.py -v`
Expected: PASS

### Task 9.2: Docker-compose deployment target
**Objective:** Provide a one-command deploy path that starts backend, frontend proxy, and optional Postgres swap-in for pgvector later.

**Files:**
- Create: `Jim/docker-compose.yml`
- Create: `backend/Dockerfile`, `frontend/Dockerfile`

**Step 1: Write docker-compose referencing existing services (SearXNG on :8080)**
```yaml
services:
  jim-backend:   build: ./backend
  jim-frontend:  build: ./frontend
  # Optional: postgres when upgrading from sqlite
```

**Step 2: Validate compose with dry-run**
Run: `docker compose config --dry-run`
Expected: valid service graph printed.

---

## Verification & acceptance criteria

Every task above ends with **PASS** in its test run — that's the gate. Before marking a phase done:
- [ ] All unit + integration tests green (`pytest -q && npm run test -- --run`)
- [ ] Backend health endpoint responds (`curl -s localhost:8765/health | jq`)
- [ ] Tauri app launches without console errors
- [ ] Chat can stream to UI with at least one citation per turn
- [ ] Settings page persists LLM endpoint across reloads
- [ ] Job progress events arrive via SSE within 2s of submission

## Risks, tradeoffs & open questions

| Risk / Tradeoff | Mitigation |
|---|---|
| Disk full (91%) — keep DB single-file, avoid Neo4j image (~1.5GB) | Use SQLite; monitor `df -h` before heavy ingest batches |
| CPU-heavy reranker blocks FastAPI worker threads | Run reranking on a separate asyncio task or background process pool |
| User LLM endpoint unavailable → graceful degradation | Return "LLM unreachable" status + cached recent answers if possible |
| Embedding model download ~100MB — network fragile | Cache under `~/.cache/jim/embeddings`; resume-friendly downloads |
| SearXNG rate limits web fallback | Expose configurable delay + queue with back-off |
| Memory pressure from concurrent jobs | Max concurrency = 2 workers; fail-fast with HTTP 503 when saturated |

**Open:** Confirm whether you want automatic PDF downloading from arXiv or just metadata + link-to-PDF in the library browser. I'll default to **metadata-only v1, auto-download as an optional toggle**. Say otherwise and I'll adjust Phase 6 Task 6.1 accordingly.
