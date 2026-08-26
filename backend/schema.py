"""Pydantic request/response models for the FastAPI layer.

Kept separate from db/models.py on purpose: those are SQLAlchemy ORM tables
(what's stored), these are API contracts (what's sent/received over HTTP).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    authors: str | None = None
    year: int | None = None
    abstract: str | None = None
    arxiv_id: str | None = None
    created_at: datetime | None = None


class AskRequest(BaseModel):
    question: str
    paper_id: int | None = None
    top_k: int = 5


class SourceOut(BaseModel):
    chunk_id: int
    paper_id: int
    page: int | None = None
    title: str | None = None
    score: float
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceOut]


class DiscoveredPaperOut(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    year: int | None = None
    pdf_url: str


class IngestArxivRequest(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str] = []
    abstract: str | None = None
    year: int | None = None
    pdf_url: str
