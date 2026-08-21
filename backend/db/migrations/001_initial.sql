-- Initial migration: create all tables for Jim PhD companion
-- Task 1.1: SQLite schema for papers library

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR NOT NULL,
    authors VARCHAR,
    year INTEGER,
    path VARCHAR NOT NULL UNIQUE,
    sha256 VARCHAR NOT NULL UNIQUE,
    arxiv_id VARCHAR UNIQUE,
    abstract TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_papers_title ON papers(title);
CREATE INDEX idx_papers_sha256 ON papers(sha256);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    title VARCHAR,
    page INTEGER,
    content TEXT NOT NULL,
    "order" INTEGER DEFAULT 0,
    image_refs VARCHAR,
    table_refs VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chunks_paper_id ON chunks(paper_id);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    vector TEXT NOT NULL,
    model VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_embeddings_chunk_id ON embeddings(chunk_id);

CREATE TABLE IF NOT EXISTS graph_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label VARCHAR NOT NULL,
    node_type VARCHAR NOT NULL,
    source_paper_id INTEGER REFERENCES papers(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_graph_nodes_label ON graph_nodes(label);
CREATE INDEX idx_graph_nodes_type ON graph_nodes(node_type);

CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node_id INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    to_node_id INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    edge_type VARCHAR NOT NULL,
    weight FLOAT DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_graph_edges_from ON graph_edges(from_node_id);
CREATE INDEX idx_graph_edges_to ON graph_edges(to_node_id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id VARCHAR NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    retrieved_chunk_ids VARCHAR,
    importance FLOAT DEFAULT 0.5,
    paper_id INTEGER REFERENCES papers(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_memories_conversation ON memories(conversation_id);
