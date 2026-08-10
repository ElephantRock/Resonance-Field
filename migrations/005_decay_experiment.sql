CREATE TABLE IF NOT EXISTS decay_retrieval_observations (
    observation_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    phase TEXT NOT NULL CHECK (phase IN ('pre', 'post')),
    neighborhood TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    trace_id UUID NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    retrieval_score DOUBLE PRECISION NOT NULL,
    current_energy DOUBLE PRECISION NOT NULL CHECK (current_energy >= 0),
    semantic_similarity DOUBLE PRECISION NOT NULL,
    trace_age_seconds DOUBLE PRECISION NOT NULL CHECK (trace_age_seconds >= 0),
    captured_at TIMESTAMPTZ NOT NULL,
    UNIQUE (run_id, cycle, phase, neighborhood, rank)
);

CREATE INDEX IF NOT EXISTS decay_retrieval_run_cycle_idx
    ON decay_retrieval_observations(run_id, cycle, phase, neighborhood, rank);
CREATE INDEX IF NOT EXISTS decay_retrieval_trace_idx
    ON decay_retrieval_observations(run_id, trace_id, cycle);

CREATE TABLE IF NOT EXISTS decay_resurrection_events (
    resurrection_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    neighborhood TEXT NOT NULL,
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    trace_id UUID NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    rank_before INTEGER NOT NULL CHECK (rank_before > 0),
    rank_after INTEGER CHECK (rank_after > 0),
    energy_before DOUBLE PRECISION NOT NULL CHECK (energy_before >= 0),
    energy_after DOUBLE PRECISION NOT NULL CHECK (energy_after >= 0),
    confirmed BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS decay_resurrection_run_idx
    ON decay_resurrection_events(run_id, cycle, neighborhood);
