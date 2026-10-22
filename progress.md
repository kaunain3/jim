# Jim — Project Progress Report

Jim is a local-first PhD research companion: ingest papers (PDF / arXiv), embed them locally, and answer questions grounded in the library through a user-provided local LLM.

**Last updated:** 2026-09 (RAG pipeline confirmed working end-to-end)

## Working Rules
- Do not run `git commit` / `git add` unless the user explicitly asks.
- Preserve user-created files and unrelated worktree changes.
- Run backend tests with `.venv/bin/pytest -q` (Windows: `uv run pytest -q`).

---

## 1. Executive Summary

| Area | Status |
|---|---|
| Backend foundations (FastAPI, SQLite, job runner, SSE) | ✅ Complete |
| PDF ingestion (extract → chunk → embed → store) | ✅ Working (redesigned this session) |
| Semantic retrieval | ✅ Working |
| RAG question answering via local LLM (Ollama) | ✅ Working end-to-end |
| arXiv discovery + one-click ingest from UI | ✅ Working |
| Web frontend (Vite + React + TS + Tailwind) | ✅ Working; Tauri shell scaffolded |
| Reranker | ❌ Not started |
| Persistent memory / conversations | ❌ Not started |
| Knowledge graph | ❌ Not started |
| SearXNG web fallback | ❌ Not started |
| OCR fallback | ⚠️ Code present, not operational |
| SSE streaming chat + citation UI polish | ⚠️ Partial (non-streaming; sources panel added) |
| Docker / e2e tests | ❌ Not started |

**Milestone this session:** the basic RAG loop works: download a paper from arXiv, ingest it, embed it, retrieve relevant chunks, and have the LLM answer from them with cited sources.

---

## 2. Architecture (as built)

```
React UI (Vite)  ──HTTP──▶  FastAPI backend
                               │
        ┌──────────────────────┼───────────────────────┐
        ▼                      ▼                       ▼
  Ingestion pipeline     Retrieval (cosine)      LLM client (httpx)
  PyMuPDF → chunking     over stored vectors     OpenAI-compatible
  → bge-small embeddings        │                 /v1/chat/completions
        └────────▶ SQLite (data/jim.db) ◀─────────┘   → Ollama (qwen2)
```

- **Storage:** SQLite via SQLAlchemy (`papers`, `chunks`, `embeddings`, `graph_nodes`, `graph_edges`, `memories`, `jobs`). Vectors stored as JSON text; cosine similarity computed in Python (v1).
- **Background work:** asyncio worker pool (2 workers), jobs persisted in SQLite, SSE progress at `/jobs/stream/{id}`.
- **LLM:** bring-your-own endpoint. Used: Ollama at `http://127.0.0.1:11434`, model `qwen2:latest`, configured by `JIM_LLM_BASE_URL` and `JIM_LLM_MODEL` env vars (per-shell in PowerShell).
- **Embeddings:** `BAAI/bge-small-en-v1.5` (384-dim, 512-token window) with query prefix via `embed_query()`.

---

## 3. Phase Status

### Phase 0: Foundations — ✅
- Monorepo layout, FastAPI skeleton, `/` and `/health`.

### Phase 1: PDF ingestion — ✅ (redesigned)
- ✅ Schema and migration (`db/migrations/001_initial.sql`), ORM models, persisted jobs.
- ✅ Background job runner with restart recovery and SSE (state replay, keepalive, unsubscribe on disconnect).
- ✅ **Ingestion redesigned this session** (see Section 4). The original heading-heuristic extractor (`services/extractor.py`, ~2,000 lines) proved fragile and produced unusable output for RAG. Ingestion now uses `services/simple_extract.py` (page-based PyMuPDF text with references stripped) plus `services/chunking.py`.
- ✅ Transactional ingest with sha256 dedup, zero-chunk guard, embedding-count validation, rollback on failure.
- ⚠️ OCR fallback: `use_ocr` flag and `_run_ocr` exist, but `unum_ocr` is not installed and no scan fixture/tests exist. Deferred by plan.

### Phase 2: Search and reranking
- ✅ Task 2.1 Embeddings: now `bge-small-en-v1.5` (was `all-MiniLM-L6-v2`). Lazy-loaded, injectable for tests.
- ❌ Task 2.2 Reranker: not started.
- ⚠️ Task 2.3 Search: `services/search.py::semantic_search` (cosine) powers RAG. `GET /papers/search` is still a keyword `ILIKE` stopgap; no dedicated `api/search.py` yet.

### Phase 3: RAG chat backend
- ✅ Task 3.1 LLM client (`httpx`, timeout raised 30s → 120s for local models).
- ✅ `POST /ask`: retrieve top-k chunks → build prompt with numbered excerpts → LLM → answer + sources. Whole-library or single-paper scope. Errors mapped to readable 502/504 (unreachable LLM, bad status, timeout).
- ⚠️ Task 3.2: not SSE-streamed; no token/citation events yet.

### Phase 4: Persistent memory — ❌ (model exists, no service)
### Phase 5: Knowledge graph — ❌ (models exist, no extractor or API)

### Phase 6: Discovery
- ✅ arXiv search (`/discover`), ingest (`/discover/ingest`), recent (`/discover/recent`).
- ❌ SearXNG web fallback.

### Phase 7–8: Frontend
- ✅ Pages: Dashboard, Papers, Paper Detail, Search, Ask, Upload, Settings (+ `RustTest`).
- ✅ **Added this session:** "Add to library" button on arXiv results; Ask page supports whole-library queries, surfaces real backend errors, and shows a **Sources** panel (title, page, excerpt).
- ⚠️ Deviation from plan: web app first; a `src-tauri/` shell (Tauri 2) now exists with a working React ↔ Rust `greet` command, but the app is not yet packaged as a desktop app.
- ❌ No streaming chat, PDF viewer with page jump, graph view, or frontend tests.

### Phase 9: Testing and packaging
- ✅ Backend unit test suite (earlier baseline: 83 passing). Not re-run in full after this session's changes; extractor tests target the original `extractor.py` and need review after the ingestion redesign.
- ❌ e2e tests, Docker Compose.

---

## 4. RAG Debugging Case Study (this session)

### Symptom
`POST /ask` returned HTTP 200 with "I couldn't find anything in your library relevant to that question yet."

### Diagnosis
That message is produced only when `semantic_search()` returns no rows, so the LLM was never called (an LLM failure would have surfaced as 502). Inspecting `data/jim.db` showed **1 paper, 0 chunks, 0 embeddings**: a paper row had been committed without any chunks. The fault was in ingestion, not the LLM or the embedder.

### Root causes identified
1. **Fragile extraction:** the heading-detection extractor produced sections that were filtered down to nothing.
2. **Oversized chunks:** one chunk per whole section, but MiniLM only reads ~256 tokens, so most text was never embedded.
3. **No zero-chunk guard:** a paper could be saved with no searchable content.
4. **Swallowed errors:** LLM failures became a bare 500, and the frontend did not check `res.ok`.
5. **Weak embedding model** for retrieval.

### Fixes
| Component | Change |
|---|---|
| `services/simple_extract.py` (new) | Per-page `get_text("text", sort=True)`, de-hyphenation, control-char cleanup, reference-section cut-off |
| `services/chunking.py` (new) | Overlapping word windows (`split_text`, 180 words / 40 overlap) |
| `services/ingest.py` | Chunk → embed `title + chunk` → store clean chunk; raise if no chunks; single transaction |
| `services/embedding.py` | `bge-small-en-v1.5`; `embed_query()` adds bge query prefix |
| `services/qa.py` | Retrieval off the event loop; tighter prompt; `[n]` citations |
| `api/chat.py` | Maps connection / status / timeout errors to 502/502/504 |
| `services/llm_client.py` | 120s timeout |
| `workers/job_runner.py` | Ingest job uses the new extraction path |
| Frontend | Error surfacing, whole-library ask, Sources panel, arXiv "Add to library" |

### Secondary incidents resolved
- `ImportError: cannot import name 'PDFExtractor'` at startup: `services/extractor.py` had been overwritten; fixed by restoring/replacing it so `PDFExtractor`, `Section`, `ExtractionResult` import again.
- A generic browser 500 during ingest/ask: diagnosed via the uvicorn traceback (browser console alone does not show the cause).

### Verification (confirmed working per user)
- Server starts cleanly.
- Paper ingested from arXiv; chunks and embeddings stored.
- Questions return grounded answers from the local LLM with source excerpts.

### Lessons learned
- Check the data (row counts) before blaming the model: an empty-retrieval message points at ingestion.
- Match chunk size to the embedder's token window.
- Surface backend errors to the UI; a silent "No answer generated" hid the real failures.
- Relative DB paths (`data/jim.db`) mean the working directory determines which database is used.
- Changing the embedding model invalidates stored vectors; re-ingest after any model change.

---

## 5. Environment Setup (reproducible)

```powershell
# Terminal 1: LLM
ollama pull qwen2
# Terminal 2: backend (from backend/)
$env:JIM_LLM_BASE_URL="http://127.0.0.1:11434"
$env:JIM_LLM_MODEL="qwen2:latest"
uv run uvicorn main:app --reload --port 8000
# Terminal 3: frontend (from frontend/)
npx vite --open
```

Diagnostic for ingestion health (from `backend/`):
```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('data/jim.db'); print(c.execute('select count(*) from chunks').fetchone(), c.execute('select count(*) from embeddings').fetchone())"
```
Chunk and embedding counts should be equal and non-zero.

---

## 6. Known Limitations
- Vector search is brute-force cosine in Python (fine for hundreds of papers; plan is sqlite-vec).
- No reranker, so top-k is by embedding similarity only.
- `/ask` is non-streaming and stateless (no conversation memory).
- Answer quality depends on the local model (qwen2 is small); prompt tuning may be needed.
- Scanned PDFs yield no text without OCR.
- Page-based chunks lose section headings (trade-off for robustness).
- Citation markers in text are not yet clickable; sources are listed below the answer.
- Settings theme not persisted; `GET /papers/search` is keyword-only.

---

## 7. Next Steps (prioritized)
1. Re-run the full test suite; update or replace extractor tests for the new ingestion path; add `test_chunking.py` and tests for `/papers/stats`, `/papers/search`, `DELETE /papers/{id}`, `/discover/recent`.
2. Add a reranker (bge-reranker-base) over the top-20 → top-5 (Task 2.2).
3. Persistent memory and conversation IDs (Phase 4).
4. SSE streaming for `/ask` with clickable citations that open the PDF at the cited page.
5. Dedicated `api/search.py` using `semantic_search`; migrate to sqlite-vec when the library grows.
6. Settings page for LLM endpoint/model and OCR toggle (currently env vars only).
7. Knowledge graph extraction and view (Phase 5, Graph UI).
8. SearXNG fallback, OCR enablement, Docker Compose, e2e tests.
9. Decide web vs. packaged Tauri desktop app and complete packaging.
10. Document local LLM setup in the README.
