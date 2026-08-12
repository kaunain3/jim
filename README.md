# jim - Your Personal PhD Companion

> A local-first AI research workspace that remembers your research, understands your literature, and keeps your work private.

Jim is an AI-powered research workspace for researchers, PhD students, and engineers. It combines **literature discovery, semantic search, persistent memory, knowledge graphs, and research-aware AI assistance** in one place.

### Why Jim?

Research is scattered across papers, notes, reference managers, AI chats, and countless browser tabs. Jim brings that information together and builds a persistent understanding of your research over time.

### Core Features

* 📚 **Literature Discovery** - Search and explore academic papers.
* 🔎 **Semantic Search** - Find research by meaning, not just keywords.
* 🧠 **Persistent Memory** - Remember projects, ideas, hypotheses, and research history.
* 🗂️ **Local Research Library** - Store and process papers locally.
* 🕸️ **Knowledge Graphs** - Connect papers, authors, methods, datasets, and concepts.
* ✍️ **Research Assistant** - Help with literature reviews, writing, research gaps, and experiments.
* 🔒 **Privacy First** - Local storage, embeddings, and LLM inference by default.

### Architecture

```text
Researcher
    ↓
Jim Desktop App
    ↓
Research + Memory Engine
    ↓
Retrieval / Embeddings / Knowledge Graph
    ↓
Local LLM
    ↓
Grounded Response
```

### Tech Stack

**Frontend:** React, TypeScript, Tailwind CSS
**Backend:** Python, FastAPI
**AI:** Ollama, llama.cpp, Hugging Face
**Storage:** SQLite, ChromaDB / FAISS
**Knowledge Graph:** Neo4j / NetworkX
**Documents:** PyMuPDF, OCR

### Project Status

🚧 **Early Development**

Jim is currently being built as a local-first research platform. Features and architecture may change as development progresses, because apparently software architecture enjoys evolving at the exact moment you've become comfortable with it.

### License

Jim is licensed under the **Apache License 2.0**.

See [`LICENSE`](LICENSE) for details.

---

**Jim**
*Your research should remain private, persistent, and context-aware.*
