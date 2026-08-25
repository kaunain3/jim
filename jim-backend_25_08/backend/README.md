# Jim — Your Personal PhD Companion

> A local-first research assistant that ingests your papers, answers questions grounded in them, and can go find new ones for you.

Jim runs entirely on your machine: papers stay on disk, embeddings stay in a local SQLite file, and the LLM is whatever you already run locally (Ollama, LM Studio, llama.cpp). Nothing is sent to the cloud.

## What it does today

- **Ingest a PDF** — upload a paper, it gets parsed (headings, tables, images, reading order), split into chunks, and embedded.
- **Ask questions about your library** — retrieval-augmented Q&A over everything you've ingested, with page-level source citations.
- **Discover new papers** — search arXiv by topic, review the results, and choose which ones to pull into your library.

This is a backend/API only right now — no frontend yet. Everything below is used via the auto-generated `/docs` page or your own HTTP client.

### Not built yet (see [Plan_overview.md](Plan_overview.md) / [Implementation_plan.md](Implementation_plan.md) for the full original scope)

- Frontend (React) / desktop shell (Tauri)
- Persistent conversation memory across turns (the `memories` table exists, unused)
- Knowledge graph extraction (the `graph_nodes` / `graph_edges` tables exist, unused)
- OCR fallback for scanned PDFs
- A real vector index (currently plain cosine similarity in Python — fine for a personal library, would need to change at large scale)

## Architecture

```
PDF file
   │
   ▼
services/extractor.py    → parses PDF into headed sections (page, text, tables, images)
   │
   ▼
services/ingest.py       → writes Paper + Chunk rows, dedups by file hash
   │
   ▼
services/embedding.py    → embeds each chunk (sentence-transformers, local, CPU)
   │
   ▼
db (SQLite)               → chunks + embeddings stored, linked by chunk_id

────────────────────────────────────────────────────

Your question
   │
   ▼
services/embedding.py    → embeds the question the same way
   │
   ▼
services/search.py       → cosine-similarity ranks stored chunk embeddings
   │
   ▼
services/qa.py           → packs top-k chunks into a prompt
   │
   ▼
services/llm_client.py   → calls your local LLM server (OpenAI-compatible)
   │
   ▼
Answer + source chunks
```

`services/discovery.py` (arXiv search) feeds the same `ingest_paper()` pipeline as a manual upload — the only difference is where the PDF file comes from.

## Tech stack

| Piece | Choice |
|---|---|
| API | FastAPI (async) |
| DB | SQLite via SQLAlchemy |
| PDF parsing | PyMuPDF |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local, CPU, ~80MB) |
| LLM | Bring-your-own OpenAI-compatible endpoint (Ollama / LM Studio / llama.cpp) |
| Paper discovery | arXiv public Atom API |
| Package/env management | [uv](https://docs.astral.sh/uv/) |

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone <your-repo-url>
cd backend
uv sync
```

This installs everything, including a **CPU-only** build of PyTorch (pinned in `pyproject.toml` via a dedicated index — without this override, `sentence-transformers` pulls the full CUDA build, which is several GB larger than necessary for a small local embedding model).

### Point Jim at a local LLM

Jim doesn't ship a model — it calls whatever OpenAI-compatible server you're already running.

```bash
# Ollama example
ollama pull llama3.1
ollama serve   # usually already running as a background service after install

export JIM_LLM_BASE_URL=http://127.0.0.1:11434   # Ollama's default port
export JIM_LLM_MODEL=llama3.1                     # must match the model you pulled exactly
```

(PowerShell: `$env:JIM_LLM_BASE_URL="http://127.0.0.1:11434"`, `$env:JIM_LLM_MODEL="llama3.1"`)

Without this, `/papers` and `/discover` still work fine — only `/ask` needs the LLM reachable.

### Run

```bash
uv run uvicorn main:app --reload --port 8765
```

First `/papers` call downloads the embedding model (~80MB, one-time, cached after). Open `http://127.0.0.1:8765/docs` for the interactive API.

## API

| Endpoint | What it does |
|---|---|
| `POST /papers` | Upload a PDF (multipart file). Extracts, chunks, embeds, stores. |
| `GET /papers` | List ingested papers. |
| `GET /papers/{id}` | Get one paper. |
| `POST /ask` | `{"question": "...", "paper_id": null, "top_k": 5}` → grounded answer + source chunks. `paper_id` optionally scopes the search to one paper. |
| `GET /discover?topic=...&max_results=10` | Search arXiv by topic. Returns candidates only — nothing is downloaded or stored. |
| `POST /discover/ingest` | Given one result from `/discover`, downloads the PDF and runs it through the same ingest pipeline as a manual upload. |

## Testing

```bash
uv run pytest tests/ -v
```

`tests/test_extractor.py` expects a few sample-PDF fixtures that aren't committed to this repo — everything else runs standalone with no external dependencies (fake embedders / mocked HTTP for LLM and arXiv calls, in-memory SQLite for DB tests).

## Project structure

```
backend/
├── api/            # FastAPI routers (HTTP layer)
│   ├── papers.py
│   ├── chat.py
│   └── discovery.py
├── services/        # business logic
│   ├── extractor.py    # PDF -> structured sections
│   ├── ingest.py        # sections -> DB rows + embeddings
│   ├── embedding.py     # text -> vectors
│   ├── search.py        # query -> ranked chunks
│   ├── qa.py             # retrieval + prompt + LLM call
│   ├── llm_client.py     # OpenAI-compatible HTTP client
│   └── discovery.py      # arXiv search + PDF download
├── db/
│   ├── models.py    # SQLAlchemy tables
│   └── engine.py     # DB connection, session dependency
├── schema.py         # Pydantic request/response models
├── config.py          # env-var settings
├── main.py             # app entrypoint
└── tests/
```

## Project status

🚧 Early development. Core ingestion, embedding-based Q&A, and arXiv discovery work end-to-end. Frontend, memory, and knowledge graph are next.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
