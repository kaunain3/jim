"""Tests for the RAG ask() function — mainly that retrieval, prompt building,
and the configured model name all get wired to the LLM client correctly."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.engine import Base
from db.models import ChunksModel, EmbeddingsModel, PapersModel
from services.embedding import EmbeddingService
from services.qa import ask


class _FakeEmbedder(EmbeddingService):
    def __init__(self):
        super().__init__(model_name="fake")

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _RecordingLLM:
    """Stands in for LLMClient; records what it was called with."""

    def __init__(self, response_text: str = "the answer"):
        self.response_text = response_text
        self.calls: list[dict] = []

    async def generate(self, messages, model="local-model", temperature=0.2):
        self.calls.append({"messages": messages, "model": model})
        return self.response_text


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


def _seed_chunk(db_session, embedder, content="cats are great"):
    paper = PapersModel(title="P", path="/tmp/p.pdf", sha256="sha-qa")
    db_session.add(paper)
    db_session.flush()
    chunk = ChunksModel(paper_id=paper.id, title="Body", page=3, content=content, order=0)
    db_session.add(chunk)
    db_session.flush()
    vector = embedder.embed([content])[0]
    db_session.add(
        EmbeddingsModel(chunk_id=chunk.id, vector=embedder.serialize(vector), model="fake")
    )
    db_session.commit()


@pytest.mark.asyncio
async def test_ask_passes_configured_model_to_llm(db_session):
    embedder = _FakeEmbedder()
    _seed_chunk(db_session, embedder)
    llm = _RecordingLLM()

    await ask(db_session, "what do cats do?", llm, embedder=embedder, model="llama3.1")

    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == "llama3.1"


@pytest.mark.asyncio
async def test_ask_returns_answer_with_sources(db_session):
    embedder = _FakeEmbedder()
    _seed_chunk(db_session, embedder)
    llm = _RecordingLLM(response_text="cats sleep a lot")

    answer = await ask(db_session, "what do cats do?", llm, embedder=embedder)

    assert answer.text == "cats sleep a lot"
    assert len(answer.sources) == 1
    assert answer.sources[0].page == 3


@pytest.mark.asyncio
async def test_ask_with_empty_library_skips_llm_call(db_session):
    embedder = _FakeEmbedder()
    llm = _RecordingLLM()

    answer = await ask(db_session, "anything?", llm, embedder=embedder)

    assert llm.calls == []
    assert "couldn't find" in answer.text
