from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import relationship
from db.engine import Base


class JobsModel(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    job_type = Column(String, nullable=False, index=True)
    kwargs_json = Column(Text, nullable=False, default="{}")
    status = Column(String, nullable=False, index=True, default="pending")
    progress = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    last_event_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class PapersModel(Base):
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    authors = Column(String, nullable=True)
    year = Column(Integer, nullable=True)
    path = Column(String, nullable=False, unique=True)
    sha256 = Column(String, nullable=False, unique=True, index=True)
    arxiv_id = Column(String, nullable=True, unique=True)
    abstract = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    chunks = relationship("ChunksModel", back_populates="paper", cascade="all, delete-orphan")
    graph_nodes = relationship("GraphNodesModel", back_populates="paper", cascade="all, delete-orphan")
    memories = relationship("MemoriesModel", back_populates="paper", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "path": self.path,
            "sha256": self.sha256,
            "abstract": self.abstract,
            "arxiv_id": self.arxiv_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChunksModel(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    title = Column(String, nullable=True)
    page = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    order = Column(Integer, nullable=False, default=0)
    image_refs = Column(String, nullable=True)  # e.g. "<img_0>,<img_2>"
    table_refs = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    paper = relationship("PapersModel", back_populates="chunks")
    embeddings = relationship("EmbeddingsModel", back_populates="chunk", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "paper_id": self.paper_id,
            "title": self.title,
            "page": self.page,
            "content": self.content,
            "order": self.order,
            "image_refs": self.image_refs,
            "table_refs": self.table_refs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EmbeddingsModel(Base):
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), nullable=False, index=True)
    vector = Column(Text, nullable=False)  # Stored as serialized JSON string or binary
    model = Column(String, nullable=True)  # e.g. "nomic-embed-text-v2"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    chunk = relationship("ChunksModel", back_populates="embeddings")

    def to_dict(self):
        return {
            "id": self.id,
            "chunk_id": self.chunk_id,
            "model": self.model,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GraphNodesModel(Base):
    __tablename__ = "graph_nodes"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False, index=True)
    node_type = Column(String, nullable=False)  # 'paper', 'author', 'method', 'concept', 'dataset'
    source_paper_id = Column(Integer, ForeignKey("papers.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    paper = relationship("PapersModel", back_populates="graph_nodes")
    edges_from = relationship(
        "GraphEdgesModel",
        foreign_keys="[GraphEdgesModel.from_node_id]",
        back_populates="node_from"
    )
    edges_to = relationship(
        "GraphEdgesModel",
        foreign_keys="[GraphEdgesModel.to_node_id]",
        back_populates="node_to"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "node_type": self.node_type,
            "source_paper_id": self.source_paper_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GraphEdgesModel(Base):
    __tablename__ = "graph_edges"

    id = Column(Integer, primary_key=True, index=True)
    from_node_id = Column(Integer, ForeignKey("graph_nodes.id"), nullable=False, index=True)
    to_node_id = Column(Integer, ForeignKey("graph_nodes.id"), nullable=False, index=True)
    edge_type = Column(String, nullable=False)  # 'cites', 'uses_method', 'related_to', 'author_of'
    weight = Column(Float, nullable=True, default=0.5)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    node_from = relationship("GraphNodesModel", foreign_keys=[from_node_id], back_populates="edges_from")
    node_to = relationship("GraphNodesModel", foreign_keys=[to_node_id], back_populates="edges_to")

    def to_dict(self):
        return {
            "id": self.id,
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "edge_type": self.edge_type,
            "weight": self.weight,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MemoriesModel(Base):
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    retrieved_chunk_ids = Column(String, nullable=True)  # Comma-separated chunk IDs
    importance = Column(Float, nullable=True, default=0.5)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    paper = relationship("PapersModel", back_populates="memories")

    def to_dict(self):
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "question": self.question,
            "answer": self.answer,
            "retrieved_chunk_ids": self.retrieved_chunk_ids,
            "importance": self.importance,
            "paper_id": self.paper_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
