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
- ✅ Task 2.1 — Embedding service implemented in `services/embedding.py`: uses `sentence-transformers/all-MiniLM-L6-v2` (384-dim), swappable via `model_name` param, lazy-loads model on first call, exposes `embed(texts)` and `embed_one(text)`.
  - ⚠️ **Environment note (2026-09-06)**: on at least one fresh clone/environment, `sentence-transformers` was not actually present in the active Python interpreter despite being expected by this task's "done" status, causing ingestion jobs to fail with `ModuleNotFoundError: No module named 'sentence_transformers'`. Fixed locally via `pip install sentence-transformers`. **Action item**: confirm `sentence-transformers` is pinned in `requirements.txt` (or equivalent) with a version, so this doesn't regress on other machines/CI.
- ❌ Task 2.2 — **NOT STARTED**: Reranker service (`services/reranker.py`) not implemented; no bge-reranker-base or fallback models (`all-MiniLM-L6-v2` cross-encoder, `mxbai-rerank-base-v1`)
- ⚠️ Task 2.3 — **PARTIALLY IMPLEMENTED**: `services/search.py` has `semantic_search()` with cosine similarity ranking in Python; a dedicated `api/search.py` router still does not exist.
  - **Update (2026-09-06)**: a `GET /papers/search?q=...&limit=...` endpoint was added directly inside `api/papers.py` to unblock the frontend's Papers page search. This is a **basic SQL `ILIKE` match over title/authors/abstract**, not the embedding-based `semantic_search()` service — the two are not yet connected. A real `api/search.py` that calls `services/search.py`'s `semantic_search()` is still outstanding if semantic (not keyword) search is required.

### Phase 3: RAG chat backend
- ✅ Task 3.1 — LLM client wrapper implemented in `services/llm_client.py`: httpx-based AsyncClient, OpenAI-compatible `/v1/chat/completions`, retry+timeout support (30s default), injectable for testing via `httpx.MockTransport`
  - ⚠️ **Runtime blocker observed (2026-09-06)**: `POST /ask` fails at runtime with `httpx.ConnectError: All connection attempts failed` when no LLM server is actually running/reachable at the configured `llm_base_url`. This is expected behavior given the current config, not a code bug — but it means the QA feature is non-functional out of the box unless a local LLM server (e.g. Ollama or an OpenAI-compatible endpoint) is running and `config.py`'s `llm_base_url`/`llm_model` point at it. **Action item**: document the expected local LLM setup (which server, which port, which model) in the README so this isn't rediscovered per-environment.
- ⚠️ Task 3.2 — **PARTIALLY IMPLEMENTED**: Chat API exists at `backend/api/chat.py` but uses **non-streaming** `/ask` POST endpoint (returns full JSON `AskResponse` with `answer` + `sources`); NOT SSE streaming as planned. No citation marker emission (`data: {"type":"token",...}` or `data: {"type":"citation","chunk_id":123}`). Response is blocking, not streamed.

### Phase 4: Persistent memory
- ❌ Task 4.1 — **NOT STARTED**: `MemoriesModel` exists in schema (`conversation_id`, `question`, `answer`, `retrieved_chunk_ids`, `importance`) but no `services/memory_retriever.py`; memory store + embedding-based retrieval not implemented; no auto-store trigger after chat turns
- ❌ Task 4.2 — **NOT STARTED**: Follow-up context builder not implemented; no conversation_id tracking or multi-turn state accumulation; no deduplication of citations across turns

### Phase 5: Knowledge graph
- ❌ Task 5.1 — **NOT STARTED**: `GraphNodesModel`/`GraphEdgesModel` in schema but no `services/graph_extractor.py`; entity extraction (author name → author node, method keywords like "transformer" → method nodes) not implemented; no LLM-extracted entities with confidence thresholds
- ❌ Task 5.2 — **NOT STARTED**: No `api/graph.py`; no `/graph/nodes/{term}` or `/graph/subgraph?ids=...` endpoints; no adjacency list or subgraph rendering support

### Phase 6: arXiv discovery + web search
- ✅ Task 6.1 — arXiv API integration complete: `services/discovery.py` with `ArxivClient.search()` (XML Atom feed parsing), `download_pdf()` (httpx async download); `api/discovery.py` with `/discover?topic=&max_results=` and `/discover/ingest` endpoints.
  - **Update (2026-09-06)**: added `GET /discover/recent?days=` to `api/discovery.py`. Note this was implemented as "papers already in the library that have a non-null `arxiv_id`, ordered by `created_at`" — i.e. recently *ingested* arXiv-sourced papers — not a live query against arXiv's own "recent submissions" feed. If the intended semantics are the latter, this needs a different implementation using `services/discovery.py`.
- ❌ Task 6.2 — **NOT STARTED**: Web search fallback via SearXNG proxy (`http://localhost:8080/search?q=...&format=json`) not implemented; no rate-limit aware queue with back-off

### Phase 7-8: Frontend
- ⚠️ **STARTED — deviates from original plan**: The plan specifies a **Tauri + React** desktop app; what currently exists (as of 2026-09-06) is a **standard web frontend** (Vite + React + TypeScript + Tailwind, running in a browser via `npx vite`, no `src-tauri/` directory, no Tauri packaging). This may be an intentional scope change (needs confirmation) or a deviation that should be reconciled with the plan before further frontend work continues.
  - **Implemented pages**: Dashboard (stats + recent papers), Papers (list + client-side search via `/papers/search`), Paper Detail (single-paper view + inline QA), Search (library search + arXiv discovery), Ask/QA (paper selector + question form, calls `/ask`), Upload (PDF upload → background job → redirect to Papers), Settings (backend health check + local light/dark theme toggle, not persisted).
  - **Implemented components**: `Header`, `Sidebar` (slide-out nav, right-anchored), `SearchBar`, `PaperCard`.
  - **Data layer**: `src/hooks/useApi.ts` — all fetch calls now point at the real backend paths (`/papers`, `/papers/stats`, `/papers/search`, `/ask`, `/discover`, `/discover/recent`, `/health`) with no `/api` prefix, matching the actual FastAPI router prefixes. Uses Vite dev-server proxy to `http://localhost:8000` for these paths.
  - **Known gaps / follow-ups**:
    - Chat UI has no SSE/streaming support (matches backend Task 3.2 being non-streaming) — plain request/response only.
    - No citation highlighting/rendering (`sources`/`SourceOut` from `/ask` responses are not yet surfaced in the UI beyond the raw answer text).
    - No Graph View (blocked on backend Phase 5 not being started).
    - Discovered-but-not-yet-ingested arXiv results link out to the raw arXiv PDF rather than triggering `/discover/ingest` from the UI — there is currently no in-app "ingest this discovered paper" action.
    - Settings page's theme toggle is local component state only; it is not persisted (no localStorage/backend setting) and resets on reload.
    - No automated frontend tests exist yet.

### Phase 9: Testing & packaging
- ✅ Unit tests — **83 passed** in `.venv/bin/pytest -q` (~4s). Coverage includes upload safety, job persistence/lifecycle, migration execution, ingestion rollback, extractor behavior, embedding, search, RAG QA, LLM client, discovery, and schemas.
  - Note: the new `GET /papers/stats`, `GET /papers/search`, `DELETE /papers/{paper_id}`, and `GET /discover/recent` endpoints added 2026-09-06 do not yet have corresponding unit tests. Recommend adding coverage for these before considering Phase 2.3/Phase 6.1 fully closed.
- ❌ **NOT STARTED**: No e2e smoke tests (`tests/test_e2e_chat.py`), no Docker Compose deployment target (`docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`)

---

## Backend Files Summary

| File | Status | Details |
|------|--------|---------|
| `backend/main.py` | ✅ | FastAPI app, routers wired (`papers`, `chat`, `discovery`, `jobs`), `Base.metadata.create_all()` on startup, `/` and `/health` endpoints |
| `backend/api/papers.py` | ✅ | `POST /papers` (upload + ingest), `GET /papers` (list), `GET /papers/{id}` (get), `DELETE /papers/{id}` (delete, cascades to chunks/graph_nodes/memories), `GET /papers/stats` (dashboard counts), `GET /papers/search?q=&limit=` (basic ILIKE keyword search — **not** the semantic search service). Fixed-path routes (`/stats`, `/search`) are declared before the `/{paper_id}` path param route to avoid FastAPI path-matching conflicts. *(stats/search/delete added 2026-09-06)* |
| `backend/api/jobs.py` | ✅ | `GET /jobs/stream/{job_id}` SSE progress streaming (state replay, keepalive, no busy-loop, unsubscribe on disconnect), `GET /jobs/{job_id}` polling. Broken `POST /jobs` placeholder removed |
| `backend/api/chat.py` | ⚠️ | `POST /ask` — non-streaming JSON response with answer + sources; NOT SSE. Runtime-dependent on a reachable LLM server (see Phase 3 note above) |
| `backend/api/discovery.py` | ✅ | `GET /discover?topic=&max_results=` (arXiv search), `POST /discover/ingest` (download + ingest), `GET /discover/recent?days=` (library papers with a non-null `arxiv_id`, recently created). *(`/recent` added 2026-09-06)* |
| `backend/workers/job_runner.py` | ✅ | Async job queue + worker pool, `Job.notify/complete/fail` with SSE broadcast, `subscribe`/`unsubscribe`, `stream_events()`. `_run_ingest` extracts once and reuses the result (no double extraction) |
| `backend/services/extractor.py` | ✅ | Full PyMuPDF extraction: triage (text layer detection, multi-column), layout-aware reading order, heading detection (font-size/bold heuristics), table extraction (find_tables + borderless fallback), image extraction (raster + vector), validation gate (abstract check, title length, suspicious headings). Async `extract()` runs CPU work in a worker thread. OCR methods present but not operational. |
| `backend/services/embedding.py` | ✅ | `EmbeddingService` with `sentence-transformers/all-MiniLM-L6-v2` (384-dim), `embed(texts)`, `embed_one(text)`, `serialize/deserialize`. Requires `sentence-transformers` installed in the active environment — see environment note above. |
| `backend/services/llm_client.py` | ✅ | `LLMClient` with httpx AsyncClient, OpenAI-compatible `/v1/chat/completions`, configurable timeout, injectable for testing. Requires a real reachable LLM server at runtime — see Phase 3 note above. |
| `backend/services/search.py` | ✅ | `semantic_search(db, query, top_k, paper_id)` — cosine similarity in Python, returns `SearchResult` list. **Not yet wired to any REST endpoint** — only called internally by `services/qa.py`. |
| `backend/services/qa.py` | ✅ | `ask(db, question, llm, top_k, paper_id)` — packs retrieved chunks into system prompt, calls LLM, returns `Answer(text, sources)` |
| `backend/services/ingest.py` | ✅ | `ingest_paper(db, pdf_path, extractor, embedder, title, authors, year, arxiv_id, abstract, extraction_result)` — ties extraction + chunking + embedding in one transaction with dedup; accepts a pre-extracted result to avoid extracting twice; embedding runs in a worker thread |
| `backend/services/discovery.py` | ✅ | `ArxivClient.search(topic, max_results)` parses Atom feed; `download_pdf(pdf_url, dest_path)` downloads to disk |
| `backend/db/models.py` | ✅ | 6 ORM models: `PapersModel`, `ChunksModel`, `EmbeddingsModel`, `GraphNodesModel`, `GraphEdgesModel`, `MemoriesModel` with relationships and `to_dict()` |
| `backend/db/engine.py` | ✅ | SQLite engine (`jim.db`), `SessionLocal`, `get_db()` dependency |
| `backend/config.py` | ✅ | Pydantic `BaseSettings` with `JIM_` env prefix: `llm_base_url`, `llm_model`, `library_dir` |
| `backend/schema.py` | ✅ | Pydantic models: `PaperOut`, `AskRequest`, `SourceOut`, `AskResponse`, `DiscoveredPaperOut`, `IngestArxivRequest`, `JobOut`, `StatsOut`, `SearchResultOut`. Dead `SubmitJobRequest` (unimported `UploadFile`) removed. *(`StatsOut`, `SearchResultOut` added 2026-09-06)* |

**Missing backend files:**
- `services/reranker.py` — Task 2.2 (bge-reranker-base + fallbacks)
- `services/memory_retriever.py` — Task 4.1 (embedding-based memory retrieval)
- `services/graph_extractor.py` — Task 5.1 (entity extraction from papers)
- `api/search.py` — dedicated FastAPI router calling `services/search.py`'s `semantic_search()` (the ad-hoc `GET /papers/search` added 2026-09-06 is a keyword-only stopgap, not this)
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

**All tests pass. Extractor tests now generate PDFs programmatically via pymupdf.**

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

## Frontend Build & API Integration (2026-09-06)

A working web frontend (Vite + React + TypeScript + Tailwind) was brought from a non-building state to a functional app talking to the live backend. This was iterative debugging across the whole stack rather than a single planned task, so it's logged here in full for anyone picking this up.

### Build/tooling fixes
- `postcss.config.js` and `tailwind.config.js` used CommonJS (`module.exports`) while `package.json` has `"type": "module"` — Node treated them as ESM and threw. Renamed both to `.cjs`.
- `index.html` was missing from the project root entirely — Vite has nothing to serve without it. Created with the correct `<script type="module" src="/src/index.tsx">` entry.
- `vite.config.ts` referenced `path`/`__dirname` without `@types/node` installed — editor-level TS errors only, not a runtime blocker, but should be fixed (`npm i --save-dev @types/node`).

### Routing/import fixes
- Several page/component imports used `../` where `./` was correct (e.g. `App.tsx` importing `./components/Header` as `../components/Header`), because `pages/`, `components/`, `hooks/` all live under `src/` as siblings, not one level up.
- Several files imported hooks from nonexistent per-hook files (e.g. `../hooks/useQA`, `../hooks/useSearch`, `../hooks/useStats`) when in fact all hooks live in a single `useApi.ts`. Fixed to import from `../hooks/useApi`.
- `useHealth` and `useDelete` were imported by `Settings.tsx`/`PaperCard.tsx` but never actually defined in `useApi.ts`. Implemented both.
- `App.tsx` called `useLocation()` directly inside the top-level `App` component, outside of `<Router>`'s context — split into an outer `App` (renders `<Router>`) and inner `AppRoutes` (renders `<Routes>` and safely calls `useLocation()`).
- Page components export named exports (`PapersPage`, `PaperDetailPage`, `SearchPage`, `QAPage`, `UploadPage`, `SettingsPage`) but `App.tsx` originally imported mismatched names (`Papers`, `PaperDetail`, etc.) — fixed all six.
- `App.tsx` rendered `<Header>` with `showMenu={true}` but never passed `onMenuToggle` and never rendered `<Sidebar>` anywhere — the hamburger button did nothing and there was no way to navigate between pages except by typing URLs. Added `sidebarOpen` state, wired the toggle, rendered `<Sidebar>` with a dimmed backdrop overlay that closes it on click.
- `Sidebar.tsx`'s open/closed animation used `translate-x-full` for the *closed* state on a `left-0`-anchored panel — for a left-anchored element this moves it *right* by its own width, landing it still on-screen (at `x: 256–512` in a 256px-wide sidebar) rather than off-screen, which looked like a sidebar "stuck in the middle" of the page. Fixed the direction logic, then later moved the panel to `right-0`/`border-l` per user preference, flipping the translate direction again accordingly.

### Component-level bugs (missing imports, wrong hook usage)
- `PaperCard.tsx` used `useState` without importing it — hard crash on every render.
- `Settings.tsx` used `useEffect` without importing it — hard crash on render.
- `Settings.tsx`'s theme toggle read `theme` state to decide the next theme *before* the state update took effect (stale-closure bug); rewritten as `applyTheme(next: 'light' | 'dark')` taking the explicit target instead of toggling off stale state.
- `Papers.tsx`, `PaperDetail.tsx`, and `QA.tsx` all destructured `const { data: ... } = usePapers()` — but `usePapers()` does not return a `data` field; it returns functions (`listPapers`, `getPaper`, etc.) that must be called and their results stored in local state. All three were silently never fetching anything. Rewritten to actually call `listPapers()` / `getPaper(id)` in a `useEffect` and store the result.
- `Papers.tsx` also had a mismatched-parens JSX bug (`))}` / `)}` doubled up) causing a Babel parse error, a missing `useNavigate` import, and misuse of `useSearchParams()` (destructured as a single value instead of the `[searchParams, setSearchParams]` tuple it actually returns).
- `PaperDetail.tsx` destructured `qaLoading` from `useQA()`'s `loading` (aliased) **and** declared its own local `const [qaLoading, setQaLoading] = useState(false)` — duplicate identifier, hard Babel parse error. Removed the alias.
- `Dashboard.tsx`'s recent-papers list used `to={`/papers/${paper.id}`}` written as a bare template literal (`` to=`/papers/${paper.id}` ``) without JSX's required `{}` wrapper — invalid JSX syntax.
- `lucide-react` was used throughout as `<Icon lucide="plus" />` (a generic icon-by-name-string component) — this is not how the installed version of `lucide-react` works; it has no such generic `Icon` component taking a string prop, causing `Cannot read properties of undefined (reading 'map')` at runtime. Every usage across `Header.tsx`, `Sidebar.tsx`, `Papers.tsx`, `Search.tsx`, `Upload.tsx`, `Settings.tsx` was switched to importing and rendering the specific named icon component (e.g. `import { Plus, X } from 'lucide-react'`). `Sidebar.tsx`'s dynamic per-item icon (`item.icon: keyof typeof icons`) now imports the `icons` map object and looks up `icons[item.icon]` at render time.

### API integration fixes
- The frontend was originally written against an imagined `/api/...`-prefixed, `{success, data}`-wrapped REST contract that does not match this backend at all. The actual backend has no `/api` prefix and returns response bodies directly (matching the Pydantic `response_model`s in `schema.py`). Rewrote every fetch call in `useApi.ts` (and a couple of hardcoded `fetch()` calls left in `Upload.tsx` and `Search.tsx` that bypassed the hooks file) to hit the real paths: `/papers`, `/papers/{id}`, `/papers/stats`, `/papers/search`, `/ask` (not `/qa`), `/discover`, `/discover/recent`, `/discover/ingest`, `/health` — with no response unwrapping.
- `vite.config.ts` needed a `server.proxy` block forwarding these paths to `http://localhost:8000` so the frontend dev server and backend could talk during local development.
- **Routing collision discovered and fixed**: the React Router page route `/papers` and the backend API route `/papers` share the same path string. Because the naive proxy config matched `/papers` for *any* request method, a direct browser navigation or refresh on `localhost:3000/papers` was being proxied straight to the FastAPI backend and returned raw JSON instead of the SPA shell. Fixed by adding a `bypass()` function to each proxy entry that inspects the `Accept` header — requests accepting `text/html` (real page navigations) are handed back to Vite to serve `index.html`; everything else (actual `fetch()`/XHR calls, which send `Accept: application/json` or similar) is proxied through as before.
- `PapersPage`/`Search.tsx`/`Dashboard.tsx` originally treated `paper.authors` as an array of `{name}` objects (`paper.authors.map(a => a.name || a)`), but the backend's `PaperOut.authors` is a single plain string. Guarded rendering to handle both shapes defensively.
- Backend gap discovered: the frontend expected `GET /papers/stats`, `GET /papers/search`, `DELETE /papers/{id}`, and `GET /discover/recent` — none of which existed on the backend at session start. Implemented all four (see Backend Files Summary above), plus added `StatsOut`/`SearchResultOut` to `schema.py`.
- `Search.tsx`'s "discover on arXiv" results were wrapped into the same `SearchResult` shape as real library results and rendered through `PaperCard`, whose detail link assumed a real DB `id` — since discovered-but-not-ingested arXiv results have no DB id yet, this produced `GET /papers/undefined → 422`. Per user preference, fixed by rendering discovered results as a visually separate list that links out to the arXiv PDF directly (`target="_blank"`) rather than attempting an in-app detail view.

### Environment/runtime issues (not code bugs, but blocked testing)
- A stale/orphaned `vite` dev server process on port 3000 (from an earlier session, listening on `[::1]` only) silently ignored several rounds of `vite.config.ts` proxy edits because it was never actually restarted — `npx vite --open` run afterward may have failed to rebind and the old process kept serving. This produced confusing, seemingly-random `<!DOCTYPE ...` JSON-parse errors that looked like proxy/cache bugs but were actually "you're talking to code from before the fix." Resolved by explicitly `taskkill /F` on the old PID and confirming a fresh `VITE vX ready` banner before continuing to debug.
- `sentence-transformers` was not installed in the backend's active Python environment (see Phase 2.1 note above) — first real end-to-end PDF upload failed inside the ingestion worker. Fixed via `pip install sentence-transformers`; flagged as a `requirements.txt` pinning gap to close.
- `POST /ask` fails with `httpx.ConnectError` because no LLM server is reachable at the configured `llm_base_url` in this environment — deferred, not yet fixed (see Phase 3 note above). QA/chat feature is not currently testable end-to-end until a local LLM server is stood up and configured.

### Current verified-working state (as of end of session)
- `npx vite --open` serves the app cleanly with no build/runtime errors on Dashboard, Papers, Paper Detail, Search, Settings.
- Uploading a PDF via the Upload page successfully creates a background ingestion job, and — once `sentence-transformers` was installed — a real paper (title, sha256, extracted text) was ingested end-to-end and appears in Papers/Dashboard/QA's paper selector.
- Duplicate-upload rejection (`ValueError: Paper already ingested`) confirmed working as intended.
- arXiv discovery search (`GET /discover?topic=...`) returns real candidates and renders correctly with outbound PDF links.
- `QA.tsx`'s "Get Answer" flow reaches the backend correctly (paper selection + question submission both work) but currently fails at the LLM call per the runtime blocker above — this is a backend/environment issue, not a frontend bug.

### Outstanding action items from this session
1. Pin `sentence-transformers` (and confirm all other runtime deps actually used, e.g. `torch`) in `requirements.txt` with versions.
2. Document/configure a working local LLM server for `POST /ask` to actually succeed.
3. Add tests for the four new backend endpoints (`/papers/stats`, `/papers/search`, `DELETE /papers/{id}`, `/discover/recent`).
4. Decide whether `GET /papers/search` should be upgraded to call `services/search.py`'s real `semantic_search()` instead of the current basic `ILIKE` stopgap, and whether a dedicated `api/search.py` router should be added per the original plan.
5. Reconcile the frontend tech-stack deviation (web app vs. planned Tauri desktop app) with the project plan.
6. Add an in-app "ingest this discovered paper" action wired to `POST /discover/ingest`, since currently the only way to add an arXiv result to the library is via the raw endpoint, not through the UI.
7. Persist the Settings page's theme choice (currently resets on reload).

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
