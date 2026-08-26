"""Semantic search over ingested paper chunks.

v1 approach: pull every (embedding, chunk) row — optionally scoped to one
paper — and rank by cosine similarity in Python. That's plenty fast for a
personal library (hundreds to low-thousands of chunks). If the library grows
past that, swap this for a sqlite-vec virtual table without changing the
public `semantic_search` signature.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from db.models import ChunksModel, EmbeddingsModel
from services.embedding import EmbeddingService, embedding_service


@dataclass
class SearchResult:
    chunk_id: int
    paper_id: int
    content: str
    page: int | None
    title: str | None
    score: float


def semantic_search(
    db: Session,
    query: str,
    top_k: int = 5,
    paper_id: int | None = None,
    embedder: EmbeddingService = embedding_service,
) -> list[SearchResult]:
    """Embed `query` and return the top_k most similar chunks."""
    query_vector = embedder.embed_one(query)

    rows_query = db.query(EmbeddingsModel, ChunksModel).join(
        ChunksModel, EmbeddingsModel.chunk_id == ChunksModel.id
    )
    if paper_id is not None:
        rows_query = rows_query.filter(ChunksModel.paper_id == paper_id)

    scored: list[SearchResult] = []
    for embedding_row, chunk in rows_query.all():
        vector = embedder.deserialize(embedding_row.vector)
        score = _cosine_similarity(query_vector, vector)
        scored.append(
            SearchResult(
                chunk_id=chunk.id,
                paper_id=chunk.paper_id,
                content=chunk.content,
                page=chunk.page,
                title=chunk.title,
                score=score,
            )
        )

    scored.sort(key=lambda result: result.score, reverse=True)
    return scored[:top_k]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
