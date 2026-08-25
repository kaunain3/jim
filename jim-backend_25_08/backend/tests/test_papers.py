"""Tests for paper ingestion — Task 1.1 TDD."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import PapersModel, ChunksModel, EmbeddingsModel, GraphNodesModel, GraphEdgesModel, MemoriesModel


@pytest.fixture(scope="session")
def db_session():
    """Provide an in-memory database session for isolated tests."""
    engine = create_engine("sqlite:///:memory:")
    from db.engine import Base
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_insert_paper(db_session):
    """Step 1: Insert a paper record and verify it can be retrieved."""
    paper = PapersModel(
        title="Test Paper",
        authors="Alice Smith",
        year=2024,
        path="/tmp/paper.pdf",
        sha256="abc123def456"
    )
    db_session.add(paper)
    db_session.commit()

    assert paper.id is not None
    retrieved = db_session.query(PapersModel).filter_by(sha256="abc123def456").first()
    assert retrieved is not None
    assert retrieved.title == "Test Paper"
    assert retrieved.authors == "Alice Smith"
    assert retrieved.year == 2024
    assert retrieved.path == "/tmp/paper.pdf"


def test_insert_chunk(db_session):
    """Verify chunks can be attached to a paper."""
    paper = PapersModel(title="Chunk Test", authors="Bob", year=2023, path="/tmp/chunk.pdf", sha256="chunk123")
    db_session.add(paper)
    db_session.commit()

    chunk = ChunksModel(
        paper_id=paper.id,
        title="Introduction",
        page=1,
        content="This is the introduction section.",
        order=0
    )
    db_session.add(chunk)
    db_session.commit()

    retrieved = db_session.query(ChunksModel).filter_by(paper_id=paper.id).first()
    assert retrieved is not None
    assert retrieved.title == "Introduction"
    assert retrieved.page == 1
    assert "introduction" in retrieved.content.lower()


def test_insert_embedding(db_session):
    """Verify embeddings can be attached to a chunk."""
    paper = PapersModel(title="Embed Test", authors="Carol", year=2024, path="/tmp/embed.pdf", sha256="embed123")
    db_session.add(paper)
    db_session.commit()

    chunk = ChunksModel(paper_id=paper.id, title="Abstract", page=1, content="Abstract text here.", order=0)
    db_session.add(chunk)
    db_session.commit()

    embedding = EmbeddingsModel(
        chunk_id=chunk.id,
        vector="[0.1, 0.2, 0.3, 0.4, 0.5]",
        model="nomic-embed-text-v2"
    )
    db_session.add(embedding)
    db_session.commit()

    retrieved = db_session.query(EmbeddingsModel).filter_by(chunk_id=chunk.id).first()
    assert retrieved is not None
    assert retrieved.model == "nomic-embed-text-v2"


def test_insert_graph_node_and_edge(db_session):
    """Verify graph nodes and edges can be created."""
    node1 = GraphNodesModel(label="Transformer", node_type="method", source_paper_id=None)
    node2 = GraphNodesModel(label="Attention Mechanism", node_type="concept", source_paper_id=None)
    db_session.add_all([node1, node2])
    db_session.commit()

    edge = GraphEdgesModel(
        from_node_id=node1.id,
        to_node_id=node2.id,
        edge_type="uses_method",
        weight=0.8
    )
    db_session.add(edge)
    db_session.commit()

    retrieved_edge = db_session.query(GraphEdgesModel).filter_by(from_node_id=node1.id).first()
    assert retrieved_edge is not None
    assert retrieved_edge.edge_type == "uses_method"
    assert retrieved_edge.weight == 0.8


def test_insert_memory(db_session):
    """Verify memory records can be stored and retrieved."""
    memory = MemoriesModel(
        conversation_id="conv_001",
        question="What is RAG?",
        answer="RAG stands for Retrieval-Augmented Generation...",
        retrieved_chunk_ids="1,2,3",
        importance=0.9
    )
    db_session.add(memory)
    db_session.commit()

    retrieved = db_session.query(MemoriesModel).filter_by(conversation_id="conv_001").first()
    assert retrieved is not None
    assert retrieved.question == "What is RAG?"
    assert "RAG" in retrieved.answer


def test_paper_to_dict(db_session):
    """Verify PaperModel.to_dict() serializes correctly."""
    paper = PapersModel(
        title="Dict Test",
        authors="Dave",
        year=2025,
        path="/tmp/dict.pdf",
        sha256="dict123"
    )
    db_session.add(paper)
    db_session.commit()

    d = paper.to_dict()
    assert d["title"] == "Dict Test"
    assert d["authors"] == "Dave"
    assert d["year"] == 2025
    assert d["sha256"] == "dict123"
    assert "created_at" in d
    assert "updated_at" in d
