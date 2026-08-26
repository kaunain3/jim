PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY,
    title VARCHAR NOT NULL,
    authors VARCHAR,
    year INTEGER,
    path VARCHAR NOT NULL UNIQUE,
    sha256 VARCHAR NOT NULL UNIQUE,
    arxiv_id VARCHAR UNIQUE,
    abstract TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    title VARCHAR,
    page INTEGER,
    content TEXT NOT NULL,
    "order" INTEGER NOT NULL DEFAULT 0,
    image_refs VARCHAR,
    table_refs VARCHAR,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY,
    chunk_id INTEGER NOT NULL REFERENCES chunks(id),
    vector TEXT NOT NULL,
    model VARCHAR,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS graph_nodes (
    id INTEGER PRIMARY KEY,
    label VARCHAR NOT NULL,
    node_type VARCHAR NOT NULL,
    source_paper_id INTEGER REFERENCES papers(id),
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY,
    from_node_id INTEGER NOT NULL REFERENCES graph_nodes(id),
    to_node_id INTEGER NOT NULL REFERENCES graph_nodes(id),
    edge_type VARCHAR NOT NULL,
    weight FLOAT DEFAULT 0.5,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    conversation_id VARCHAR NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    retrieved_chunk_ids VARCHAR,
    importance FLOAT DEFAULT 0.5,
    paper_id INTEGER REFERENCES papers(id),
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS jobs (
    id VARCHAR PRIMARY KEY,
    job_type VARCHAR NOT NULL,
    kwargs_json TEXT NOT NULL DEFAULT '{}',
    status VARCHAR NOT NULL DEFAULT 'pending',
    progress FLOAT NOT NULL DEFAULT 0.0,
    error TEXT,
    result_json TEXT,
    last_event_json TEXT,
    created_at DATETIME,
    completed_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_papers_title ON papers(title);
CREATE INDEX IF NOT EXISTS ix_papers_sha256 ON papers(sha256);
CREATE INDEX IF NOT EXISTS ix_chunks_paper_id ON chunks(paper_id);
CREATE INDEX IF NOT EXISTS ix_embeddings_chunk_id ON embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS ix_graph_nodes_label ON graph_nodes(label);
CREATE INDEX IF NOT EXISTS ix_graph_edges_from_node_id ON graph_edges(from_node_id);
CREATE INDEX IF NOT EXISTS ix_graph_edges_to_node_id ON graph_edges(to_node_id);
CREATE INDEX IF NOT EXISTS ix_memories_conversation_id ON memories(conversation_id);
CREATE INDEX IF NOT EXISTS ix_jobs_job_type ON jobs(job_type);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);
