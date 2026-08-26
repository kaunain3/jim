"""Tests for ingest_paper — ties extraction, chunking, and embedding together."""
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.engine import Base
from db.models import ChunksModel, EmbeddingsModel, PapersModel
from services.embedding import EmbeddingService
from services.extractor import ExtractionResult, PDFExtractor, Section
from services.ingest import ingest_paper


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
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Introduction", fontsize=20)
    page.insert_text((72, 115), "This section explains the research project.", fontsize=11)
    document.save(pdf_path)
    document.close()
    return pdf_path


class _FakeEmbedder(EmbeddingService):
    def __init__(self):
        super().__init__(model_name="fake")

    def embed(self, texts):
        return [[float(len(text)), 1.0] for text in texts]


class _ShortEmbedder(_FakeEmbedder):
    def embed(self, texts):
        return super().embed(texts[:1])


class _FailingEmbedder(_FakeEmbedder):
    def embed(self, texts):
        raise RuntimeError("embedding failed")


@pytest.mark.asyncio
async def test_ingest_paper_creates_paper_chunks_and_embeddings(db_session, sample_pdf):
    paper = await ingest_paper(
        db_session, sample_pdf, PDFExtractor(), embedder=_FakeEmbedder(), title="Sample"
    )

    assert paper.id is not None
    assert paper.title == "Sample"
    assert paper.sha256

    chunks = db_session.query(ChunksModel).filter_by(paper_id=paper.id).all()
    assert len(chunks) > 0

    embeddings = (
        db_session.query(EmbeddingsModel)
        .join(ChunksModel)
        .filter(ChunksModel.paper_id == paper.id)
        .all()
    )
    assert len(embeddings) == len(chunks)
    assert all(embedding.model == "fake" for embedding in embeddings)


@pytest.mark.asyncio
async def test_ingest_paper_rejects_duplicate_sha256(db_session, sample_pdf):
    embedder = _FakeEmbedder()
    await ingest_paper(db_session, sample_pdf, PDFExtractor(), embedder=embedder, title="Sample")

    with pytest.raises(ValueError):
        await ingest_paper(
            db_session, sample_pdf, PDFExtractor(), embedder=embedder, title="Sample again"
        )


@pytest.mark.asyncio
async def test_ingest_paper_missing_file_raises(db_session, tmp_path):
    with pytest.raises(FileNotFoundError):
        await ingest_paper(
            db_session, tmp_path / "missing.pdf", PDFExtractor(), embedder=_FakeEmbedder()
        )


@pytest.mark.asyncio
async def test_ingest_rejects_empty_extraction_without_creating_paper(
    db_session, sample_pdf
):
    with pytest.raises(ValueError, match="No extractable text"):
        await ingest_paper(
            db_session,
            sample_pdf,
            PDFExtractor(),
            embedder=_FakeEmbedder(),
            extraction_result=ExtractionResult(),
        )

    assert db_session.query(PapersModel).count() == 0


@pytest.mark.asyncio
async def test_ingest_rejects_embedding_count_mismatch_and_rolls_back(
    db_session, sample_pdf
):
    result = ExtractionResult(
        sections=[
            Section("Introduction", 1, "First chunk", 0),
            Section("Methods", 1, "Second chunk", 1),
        ]
    )

    with pytest.raises(ValueError, match="Embedding count mismatch"):
        await ingest_paper(
            db_session,
            sample_pdf,
            PDFExtractor(),
            embedder=_ShortEmbedder(),
            extraction_result=result,
        )

    assert db_session.query(PapersModel).count() == 0
    assert db_session.query(ChunksModel).count() == 0
    assert db_session.query(EmbeddingsModel).count() == 0


@pytest.mark.asyncio
async def test_ingest_rolls_back_when_embedding_fails(db_session, sample_pdf):
    result = ExtractionResult(
        sections=[Section("Introduction", 1, "A valid chunk", 0)]
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        await ingest_paper(
            db_session,
            sample_pdf,
            PDFExtractor(),
            embedder=_FailingEmbedder(),
            extraction_result=result,
        )

    assert db_session.query(PapersModel).count() == 0
    assert db_session.query(ChunksModel).count() == 0
