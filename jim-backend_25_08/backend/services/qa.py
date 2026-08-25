"""Retrieval-augmented Q&A over the ingested paper library."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from services.embedding import EmbeddingService, embedding_service
from services.llm_client import LLMClient
from services.search import SearchResult, semantic_search

SYSTEM_PROMPT = (
    "You are Jim, a research assistant. Answer the user's question using ONLY "
    "the provided excerpts from their paper library. Cite sources inline using "
    "[cite:N], where N is the excerpt number. If the excerpts don't contain "
    "the answer, say so plainly instead of guessing."
)


@dataclass
class Answer:
    text: str
    sources: list[SearchResult]


async def ask(
    db: Session,
    question: str,
    llm: LLMClient,
    top_k: int = 5,
    paper_id: int | None = None,
    embedder: EmbeddingService = embedding_service,
    model: str = "local-model",
) -> Answer:
    sources = semantic_search(db, question, top_k=top_k, paper_id=paper_id, embedder=embedder)

    if not sources:
        return Answer(
            text="I couldn't find anything in your library relevant to that question yet.",
            sources=[],
        )

    excerpts = "\n\n".join(
        f"[{index + 1}] (page {source.page}) {source.content}"
        for index, source in enumerate(sources)
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Excerpts:\n{excerpts}\n\nQuestion: {question}"},
    ]
    text = await llm.generate(messages, model=model)
    return Answer(text=text, sources=sources)
