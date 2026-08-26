# Pi Agent Instructions

## Git Commit Policy

**NEVER commit changes on your own unless explicitly told to do so by the user.**

Only commit when the user says:
- "commit this"
- "commit the changes"
- "git commit"
- Or similar explicit instruction

Default behavior: make changes, but do NOT run `git commit` or `git add` without explicit permission.

---

## Implementation Plan Status Overview

### Phase 0: Project foundations & tooling
- ✅ Task 0.1 — Monorepo layout created (backend/, plan/, .gitignore, pyproject.toml)
- ✅ Task 0.2 — FastAPI skeleton + health check (`/health`, `/`) implemented in `backend/main.py`

### Phase 1: PDF ingestion pipeline
- ✅ Task 1.1 — SQLite schema complete: paper, chunk, embedding, graph, memory, and persisted job models are defined; `db/migrations/001_initial.sql` provides the versioned schema; the database defaults to `data/jim.db`
- ✅ Task 1.2 (non-OCR) — PDF extraction fully implemented in `services/extractor.py`: multi-column handling, heading detection via font-size/-bold heuristics, table extraction (PyMuPDF `find_tables` + fallback borderless detection), image extraction (raster + vector), and validation. CPU-bound extraction runs through `asyncio.to_thread`. Ingestion rejects PDFs without extractable text, validates one embedding per chunk, and rolls back failed transactions.
- ⚠️ Task 1.2 (OCR fallback) — **PARTIALLY IMPLEMENTED, NOT OPERATIONAL**: Code structure exists in `extractor.py`:
  - `extract()` accepts `use_ocr=False` parameter
  - `_run_ocr()` method calls `unum_ocr.process_pdf()` when `use_ocr=True`
  - `_existing_file_path()` and `_normalise_ocr_text()` helpers exist
  - When `use_ocr=False` and PDF has no text layer, returns empty `ExtractionResult()` (graceful degradation)
  - **BLOCKERS**: `unum_ocr` package is NOT installed in `.venv`; no OCR test fixture PDFs exist (`tests/fixtures/scan_only.pdf` missing); no OCR path has passing tests
  - Per plan: "Deferred until the non-OCR pipeline is stable and `unum_ocr` is selected/installed"
- ✅ Task 1.3 — Background runner and SSE progress endpoint are implemented. Job status is persisted in SQLite, interrupted pending/running jobs are restored after restart, SSE supports state replay/keepalive/terminal cleanup, and FastAPI lifespan shutdown awaits worker cancellation.
- ✅ Task 1.3 (tests) — Full suite: **83 passed** in `.venv/bin/pytest -q`, including upload safety, rollback, migration, persistence, lifecycle, and extraction regressions.

### Phase 2: Semantic search + reranking
- ✅ Task 2.1 — Embedding service implemented in `services/embedding.py`: uses `sentence-transformers/all-MiniLM-L6-v2` (384-dim), swappable via `model_name` param, lazy-loads model on first call, exposes `embed(texts)` and `embed_one(text)`
- ❌ Task 2.2 — **NOT STARTED**: Reranker service (`services/reranker.py`) not implemented; no bge-reranker-base or fallback models (`all-MiniLM-L6-v2` cross-encoder, `mxbai-rerank-base-v1`)
- ⚠️ Task 2.3 — **PARTIALLY IMPLEMENTED**: `services/search.py` has `semantic_search()` with cosine similarity ranking in Python; however **no FastAPI router** (`api/search.py` missing) — search is only called internally by the QA service, not exposed as a standalone REST endpoint

### Phase 3: RAG chat backend
- ✅ Task 3.1 — LLM client wrapper implemented in `services/llm_client.py`: httpx-based AsyncClient, OpenAI-compatible `/v1/chat/completions`, retry+timeout support (30s default), injectable for testing via `httpx.MockTransport`
- ⚠️ Task 3.2 — **PARTIALLY IMPLEMENTED**: Chat API exists at `backend/api/chat.py` but uses **non-streaming** `/ask` POST endpoint (returns full JSON `AskResponse` with `answer` + `sources`); NOT SSE streaming as planned. No citation marker emission (`data: {"type":"token",...}` or `data: {"type":"citation","chunk_id":123}`). Response is blocking, not streamed.

### Phase 4: Persistent memory
- ❌ Task 4.1 — **NOT STARTED**: `MemoriesModel` exists in schema (`conversation_id`, `question`, `answer`, `retrieved_chunk_ids`, `importance`) but no `services/memory_retriever.py`; memory store + embedding-based retrieval not implemented; no auto-store trigger after chat turns
- ❌ Task 4.2 — **NOT STARTED**: Follow-up context builder not implemented; no conversation_id tracking or multi-turn state accumulation; no deduplication of citations across turns

### Phase 5: Knowledge graph
- ❌ Task 5.1 — **NOT STARTED**: `GraphNodesModel`/`GraphEdgesModel` in schema but no `services/graph_extractor.py`; entity extraction (author name → author node, method keywords like "transformer" → method nodes) not implemented; no LLM-extracted entities with confidence thresholds
- ❌ Task 5.2 — **NOT STARTED**: No `api/graph.py`; no `/graph/nodes/{term}` or `/graph/subgraph?ids=...` endpoints; no adjacency list or subgraph rendering support

### Phase 6: arXiv discovery + web search
- ✅ Task 6.1 — arXiv API integration complete: `services/discovery.py` with `ArxivClient.search()` (XML Atom feed parsing), `download_pdf()` (httpx async download); `api/discovery.py` with `/discover?q=&max_results=` and `/discover/ingest` endpoints
- ❌ Task 6.2 — **NOT STARTED**: Web search fallback via SearXNG proxy (`http://localhost:8080/search?q=...&format=json`) not implemented; no rate-limit aware queue with back-off

### Phase 7-8: Frontend (Tauri + React)
- ❌ **NOT STARTED**: No `frontend/` or `src-tauri/` directories exist anywhere in the project. Settings panel (LLM endpoint config, reranker model selector, OCR toggle), Chat UI (SSE streaming, progress indicators, citation highlights), Graph View (React Flow), citation parsing (`parseCitations()`) all pending.

### Phase 9: Testing & packaging
- ✅ Unit tests — **83 passed** in `.venv/bin/pytest -q` (~4s). Coverage includes upload safety, job persistence/lifecycle, migration execution, ingestion rollback, extractor behavior, embedding, search, RAG QA, LLM client, discovery, and schemas.
- ❌ **NOT STARTED**: No e2e smoke tests (`tests/test_e2e_chat.py`), no Docker Compose deployment target (`docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`)

---

## Backend Files Summary

| File | Status | Details |
|------|--------|---------|
| `backend/main.py` | ✅ | FastAPI app, routers wired (`papers`, `chat`, `discovery`, `jobs`), `Base.metadata.create_all()` on startup, `/` and `/health` endpoints |
| `backend/api/papers.py` | ✅ | `POST /papers` (upload + ingest), `GET /papers` (list), `GET /papers/{id}` (get). Duplicate route definitions removed (2026-08-26) |
| `backend/api/jobs.py` | ✅ | `GET /jobs/stream/{job_id}` SSE progress streaming (state replay, keepalive, no busy-loop, unsubscribe on disconnect), `GET /jobs/{job_id}` polling. Broken `POST /jobs` placeholder removed |
| `backend/api/chat.py` | ⚠️ | `POST /ask` — non-streaming JSON response with answer + sources; NOT SSE |
| `backend/api/discovery.py` | ✅ | `GET /discover?q=&max_results=` (arXiv search), `POST /discover/ingest` (download + ingest) |
| `backend/workers/job_runner.py` | ✅ | Async job queue + worker pool, `Job.notify/complete/fail` with SSE broadcast, `subscribe`/`unsubscribe`, `stream_events()`. `_run_ingest` extracts once and reuses the result (no double extraction) |
| `backend/services/extractor.py` | ✅ | Full PyMuPDF extraction: triage (text layer detection, multi-column), layout-aware reading order, heading detection (font-size/bold heuristics), table extraction (find_tables + borderless fallback), image extraction (raster + vector), validation gate (abstract check, title length, suspicious headings). Async `extract()` runs CPU work in a worker thread. OCR methods present but not operational. |
| `backend/services/embedding.py` | ✅ | `EmbeddingService` with `sentence-transformers/all-MiniLM-L6-v2` (384-dim), `embed(texts)`, `embed_one(text)`, `serialize/deserialize` |
| `backend/services/llm_client.py` | ✅ | `LLMClient` with httpx AsyncClient, OpenAI-compatible `/v1/chat/completions`, configurable timeout, injectable for testing |
| `backend/services/search.py` | ✅ | `semantic_search(db, query, top_k, paper_id)` — cosine similarity in Python, returns `SearchResult` list |
| `backend/services/qa.py` | ✅ | `ask(db, question, llm, top_k, paper_id)` — packs retrieved chunks into system prompt, calls LLM, returns `Answer(text, sources)` |
| `backend/services/ingest.py` | ✅ | `ingest_paper(db, pdf_path, extractor, embedder, title, authors, year, arxiv_id, abstract, extraction_result)` — ties extraction + chunking + embedding in one transaction with dedup; accepts a pre-extracted result to avoid extracting twice; embedding runs in a worker thread |
| `backend/services/discovery.py` | ✅ | `ArxivClient.search(topic, max_results)` parses Atom feed; `download_pdf(pdf_url, dest_path)` downloads to disk |
| `backend/db/models.py` | ✅ | 6 ORM models: `PapersModel`, `ChunksModel`, `EmbeddingsModel`, `GraphNodesModel`, `GraphEdgesModel`, `MemoriesModel` with relationships and `to_dict()` |
| `backend/db/engine.py` | ✅ | SQLite engine (`Jim_db.db`), `SessionLocal`, `get_db()` dependency |
| `backend/config.py` | ✅ | Pydantic `BaseSettings` with `JIM_` env prefix: `llm_base_url`, `llm_model`, `library_dir` |
| `backend/schema.py` | ✅ | Pydantic models: `PaperOut`, `AskRequest`, `SourceOut`, `AskResponse`, `DiscoveredPaperOut`, `IngestArxivRequest`, `JobOut`. Dead `SubmitJobRequest` (unimported `UploadFile`) removed |

**Missing backend files:**
- `services/reranker.py` — Task 2.2 (bge-reranker-base + fallbacks)
- `services/memory_retriever.py` — Task 4.1 (embedding-based memory retrieval)
- `services/graph_extractor.py` — Task 5.1 (entity extraction from papers)
- `api/search.py` — FastAPI router for standalone search endpoint
- `api/graph.py` — FastAPI router for graph queries
- `tests/fixtures/two_column.pdf` — fixture PDF for two-column extraction tests
- `tests/fixtures/scan_only.pdf` — fixture PDF for OCR tests
- `sample1.pdf`, `sample2.pdf`, `sample7.pdf` — real paper samples for regression tests

---

## Test Results Detail

```
============================= test session started ==============================
collected 75 items

tests/test_discovery.py .....                  [OK] — feed parsing, search endpoint, PDF download, HTTP errors
tests/test_embedding.py .....                  [OK] — embed returns vectors, deterministic, serialize round-trip
tests/test_extractor.py .......................... [OK] — 31 tests, all self-contained (no fixture dependencies)
tests/test_ingest.py ...                       [OK] — paper+chunks+embeddings created, duplicate rejection, missing file
tests/test_job_runner.py .......               [OK] — job submission, SSE streaming, status transitions
tests/test_papers.py ........                  [OK] — paper CRUD, chunk/embedding insertion, graph nodes/edges, memories
tests/test_qa.py ...                           [OK] — model wiring, sources returned, empty library skip
tests/test_schema.py ...                       [OK] — PaperOut datetime serialization, from_attributes
tests/test_search.py ....                      [OK] — ranking, top_k, per-paper filtering, empty library
=========================== 75 passed in 3.04s ===========================
```

**All tests pass. Extractor tests now generate PDFs programmatically via pymupdf.

---

## Phase 1 Verification & Fixes (2026-08-26)

Full check of Phase 1 against a live uvicorn server (not just unit tests). All bugs below were reproduced live, fixed, and re-verified.

### SSE `/jobs/stream/{job_id}` — 4 bugs

1. **Missing `JobStatus` import** — `NameError` as soon as the terminal-state check ran.
2. **Subscribe-after-complete hang** — the generator only reacted to future notify events and never replayed current state. Subscribing after the job finished blocked forever on `event.wait()`. Live proof: all 5 job notifies fired with `subscribers=0` before the SSE client connected; the stream then hung for 55s.
3. **Busy-loop flood** — the event was never cleared, so after the first notify the generator spun at full CPU re-emitting the same payload. Isolated repro produced 1.27M duplicate events.
4. **No keepalive + subscriber leak** — idle connections were at the mercy of proxies; subscriber events were never removed from the Job.

**Fix** (`api/jobs.py` rewritten): `event.clear()` before each wait, current-state replay on every wake, terminal check before waiting, 15s keepalive comment, dedup of unchanged payloads, `unsubscribe()` in `finally`. Added `Job.unsubscribe` / `JobRunner.unsubscribe` in `workers/job_runner.py`.

### Other fixes

- **`/health` endpoint missing** — claimed in Task 0.2 but only `/` existed. Added to `main.py`.
- **Double extraction per job** — `_run_ingest` extracted, then `ingest_paper` extracted the same PDF again (first result discarded). `ingest_paper` now accepts `extraction_result` and skips re-extraction. Verified: exactly 1 extraction call per job.
- **Event loop blocked during ingest** — extraction (PyMuPDF) and embedding (SentenceTransformer) are synchronous but ran on the async loop, freezing SSE and every other endpoint for the job's duration. `extractor.extract()` now runs its sync core via `asyncio.to_thread`; embedding uses `asyncio.to_thread` too. SSE now streams during a 21s real-paper ingest.
- **Duplicate routes in `api/papers.py`** — `list_papers` / `get_paper` defined twice. Removed.
- **Broken `POST /jobs` placeholder** — signature `file: str = ""` could never receive a file; always failed with `pdf_path is required`. Removed (real upload path is `POST /papers`). Also removed dead `SubmitJobRequest` from `schema.py` (referenced unimported `UploadFile`).

### Live verification results

| Scenario | Before | After |
|---|---|---|
| `/health` | 404 | `{"status":"ok"}` |
| Mid-run subscribe (real paper, ~21s job) | nothing; event loop blocked | `10% → 40% → keepalive → 100% result → end`, exit 0 |
| Subscribe-after-complete | hangs forever | immediate replay of final event + `end`, exit 0 |
| Stream for unknown job | — | 404 with detail |
| `POST /jobs` | always fails | 404 (removed) |
| Route list | duplicate `/papers` handlers | clean, no dupes |

Unit tests: **75 passed**.

---

## OCR Status Detail

**Current state: Code present but not operational**

The `extractor.py` has OCR support structurally:
- `extract(pdf_path, use_ocr=False, output_root="data/library")` — parameter exists
- `_run_ocr(pdf_path)` — calls `unum_ocr.process_pdf(str(pdf_path))`
- `_existing_file_path(value)` — validates returned path is a real file
- `_normalise_ocr_text(value)` — normalizes dict/string/attribute OCR output to stripped string

When `use_ocr=False` and PDF has no text layer (triage detects `has_text_layer=False`):
- Returns empty `ExtractionResult()` — no crash, just empty

When `use_ocr=True` and PDF has no text layer:
- Calls `_run_ocr()` → imports `unum_ocr` → calls `process_pdf()`
- If `unum_ocr` not installed → raises `RuntimeError("OCR was requested, but unum_ocr is not installed.")`
- If `unum_ocr` installed but returns non-file → falls back to `_normalise_ocr_text()` → may produce `Section(page=1, text=ocr_text)`

**Blockers preventing OCR from working:**
1. `unum_ocr` package NOT installed in `.venv` (not in site-packages)
2. No fixture PDFs for OCR testing (`tests/fixtures/scan_only.pdf` missing)
3. No tests exercise the `use_ocr=True` code path
4. Plan explicitly defers this: "Keep OCR out of v1 default pipeline"

**To make OCR operational, need:**
- Install `unum_ocr` via `uv add unum-ocr`
- Add scan-only fixture PDF to `tests/fixtures/`
- Add test: `test_extract_with_ocr_returns_sections(scan_pdf)`
- Consider adding Settings UI toggle for `use_ocr` (currently only programmatic)

---

## Working Rules

- Do not commit changes unless the user explicitly requests a commit.
- Preserve user-created files and unrelated worktree changes.
- Test baseline: 83 passed (~4s) with `.venv/bin/pytest -q`
- OCR: code present but blocked on `unum_ocr` installation and fixture files
