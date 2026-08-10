CREATE TABLE IF NOT EXISTS reputation_states (
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    dimension TEXT NOT NULL,
    context_key TEXT NOT NULL,
    alpha DOUBLE PRECISION NOT NULL CHECK (alpha > 0),
    beta DOUBLE PRECISION NOT NULL CHECK (beta > 0),
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (agent_id, dimension, context_key)
);

CREATE TABLE IF NOT EXISTS reputation_evidence (
    evidence_id UUID PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    dimension TEXT NOT NULL,
    context_key TEXT NOT NULL,
    positive BOOLEAN NOT NULL,
    weight DOUBLE PRECISION NOT NULL CHECK (weight > 0),
    alpha_before DOUBLE PRECISION NOT NULL CHECK (alpha_before > 0),
    beta_before DOUBLE PRECISION NOT NULL CHECK (beta_before > 0),
    alpha_after DOUBLE PRECISION NOT NULL CHECK (alpha_after > 0),
    beta_after DOUBLE PRECISION NOT NULL CHECK (beta_after > 0),
    source_type TEXT NOT NULL,
    source_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (agent_id, dimension, context_key, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS reputation_evidence_agent_idx
    ON reputation_evidence(agent_id, dimension, context_key, created_at);

CREATE TABLE IF NOT EXISTS reputation_delegation_outcomes (
    outcome_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    regime INTEGER NOT NULL CHECK (regime IN (0, 1)),
    task_id UUID NOT NULL REFERENCES market_tasks(task_id) ON DELETE CASCADE,
    task_domain TEXT NOT NULL,
    required_skill TEXT NOT NULL,
    winner_agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    winner_bid_id UUID NOT NULL REFERENCES market_bids(bid_id) ON DELETE CASCADE,
    baseline_score DOUBLE PRECISION NOT NULL,
    reputation_score DOUBLE PRECISION NOT NULL CHECK (reputation_score BETWEEN 0 AND 1),
    total_score DOUBLE PRECISION NOT NULL,
    evidence_signal DOUBLE PRECISION NOT NULL CHECK (evidence_signal >= 0),
    practice_before INTEGER NOT NULL CHECK (practice_before >= 0),
    success_probability DOUBLE PRECISION NOT NULL CHECK (success_probability BETWEEN 0 AND 1),
    outcome_roll DOUBLE PRECISION NOT NULL CHECK (outcome_roll BETWEEN 0 AND 1),
    success BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (run_id, cycle)
);

CREATE TABLE IF NOT EXISTS reputation_auction_scores (
    run_id UUID NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    task_id UUID NOT NULL REFERENCES market_tasks(task_id) ON DELETE CASCADE,
    bid_id UUID NOT NULL REFERENCES market_bids(bid_id) ON DELETE CASCADE,
    bidder_agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    task_domain TEXT NOT NULL,
    required_skill TEXT NOT NULL,
    baseline_score DOUBLE PRECISION NOT NULL,
    reputation_score DOUBLE PRECISION NOT NULL CHECK (reputation_score BETWEEN 0 AND 1),
    evidence_signal DOUBLE PRECISION NOT NULL CHECK (evidence_signal >= 0),
    total_score DOUBLE PRECISION NOT NULL,
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    captured_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, bid_id)
);

CREATE INDEX IF NOT EXISTS reputation_outcomes_run_cycle_idx
    ON reputation_delegation_outcomes(run_id, cycle);
CREATE INDEX IF NOT EXISTS reputation_scores_run_task_idx
    ON reputation_auction_scores(run_id, task_id, total_score DESC);
