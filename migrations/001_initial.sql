CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS traces (
    trace_id UUID PRIMARY KEY,
    author_agent_id UUID,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    initial_energy DOUBLE PRECISION NOT NULL CHECK (initial_energy >= 0),
    energy_anchor DOUBLE PRECISION NOT NULL CHECK (energy_anchor >= 0),
    energy_updated_at TIMESTAMPTZ NOT NULL,
    half_life_seconds DOUBLE PRECISION NOT NULL CHECK (half_life_seconds > 0),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
    quality_score DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (quality_score BETWEEN 0 AND 1),
    adoption_score DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (adoption_score BETWEEN 0 AND 1),
    context_score DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (context_score BETWEEN 0 AND 1),
    exploration_bonus DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (exploration_bonus BETWEEN 0 AND 1),
    repetition_penalty DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (repetition_penalty BETWEEN 0 AND 1),
    status TEXT NOT NULL DEFAULT 'active',
    safety_class TEXT NOT NULL DEFAULT 'standard',
    visibility TEXT NOT NULL DEFAULT 'shared'
);

CREATE TABLE IF NOT EXISTS trace_relations (
    parent_trace_id UUID NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    child_trace_id UUID NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (parent_trace_id, child_trace_id, relation_type),
    CHECK (parent_trace_id <> child_trace_id)
);

CREATE TABLE IF NOT EXISTS trace_reinforcements (
    reinforcement_id UUID PRIMARY KEY,
    trace_id UUID NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    actor_agent_id UUID,
    kind TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL CHECK (amount >= 0),
    energy_before DOUBLE PRECISION NOT NULL CHECK (energy_before >= 0),
    energy_after DOUBLE PRECISION NOT NULL CHECK (energy_after >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS traces_created_at_idx ON traces (created_at);
CREATE INDEX IF NOT EXISTS traces_kind_idx ON traces (kind);
CREATE INDEX IF NOT EXISTS trace_relations_child_idx ON trace_relations (child_trace_id);
CREATE INDEX IF NOT EXISTS trace_reinforcements_trace_idx
    ON trace_reinforcements (trace_id, created_at);
CREATE INDEX IF NOT EXISTS traces_embedding_hnsw_idx
    ON traces USING hnsw (embedding vector_cosine_ops);
