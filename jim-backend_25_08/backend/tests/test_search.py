"""Tests for semantic_search — ranking, top_k, and per-paper filtering."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.engine import Base
from db.models import ChunksModel, EmbeddingsModel, PapersModel
from services.embedding import EmbeddingService
from services.search import semantic_search


class _FakeEmbedder(EmbeddingService):
    """Hand-picked vectors so similarity ranking is predictable."""

    VECTORS = {
        "cats": [1.0, 0.0],
        "dogs": [0.0, 1.0],
        "cat query": [0.9, 0.1],
    }

    def __init__(self):
        super().__init__(model_name="fake")

    def embed(self, texts):
        return [list(self.VECTORS.get(text, [0.0, 0.0])) for text in texts]


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def embedder():
    return _FakeEmbedder()


def _seed_chunk(db_session, embedder, content, sha):
    paper = PapersModel(title=f"Paper {sha}", path=f"/tmp/{sha}.pdf", sha256=sha)
    db_session.add(paper)
    db_session.flush()

    chunk = ChunksModel(paper_id=paper.id, title="Body", page=1, content=content, order=0)
    db_session.add(chunk)
    db_session.flush()

    vector = embedder.embed([content])[0]
    db_session.add(
        EmbeddingsModel(chunk_id=chunk.id, vector=embedder.serialize(vector), model="fake")
    )
    db_session.commit()
    return paper, chunk


def test_ranks_closest_match_first(db_session, embedder):
    _seed_chunk(db_session, embedder, "cats", sha="cats-sha")
    _seed_chunk(db_session, embedder, "dogs", sha="dogs-sha")

    results = semantic_search(db_session, "cat query", top_k=2, embedder=embedder)

    assert len(results) == 2
    assert results[0].content == "cats"
    assert results[0].score > results[1].score


def test_respects_top_k(db_session, embedder):
    for i in range(5):
        _seed_chunk(db_session, embedder, "dogs", sha=f"sha-{i}")

    results = semantic_search(db_session, "cat query", top_k=3, embedder=embedder)
    assert len(results) == 3


def test_filters_by_paper_id(db_session, embedder):
    paper1, _ = _seed_chunk(db_session, embedder, "cats", sha="p1")
    _seed_chunk(db_session, embedder, "dogs", sha="p2")

    results = semantic_search(
        db_session, "cat query", top_k=5, paper_id=paper1.id, embedder=embedder
    )

    assert len(results) == 1
    assert results[0].paper_id == paper1.id


def test_empty_library_returns_empty_list(db_session, embedder):
    assert semantic_search(db_session, "cat query", embedder=embedder) == []
