CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    ablation TEXT NOT NULL,
    seed BIGINT NOT NULL,
    config_hash TEXT NOT NULL,
    config JSONB NOT NULL,
    code_sha TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    cycles_requested INTEGER NOT NULL CHECK (cycles_requested > 0),
    cycles_completed INTEGER NOT NULL DEFAULT 0 CHECK (cycles_completed >= 0),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    failure TEXT
);

CREATE TABLE IF NOT EXISTS experiment_agents (
    run_id UUID NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    agent_slot INTEGER NOT NULL CHECK (agent_slot >= 0),
    initial_credits BIGINT NOT NULL CHECK (initial_credits >= 0),
    PRIMARY KEY (run_id, agent_id),
    UNIQUE (run_id, agent_slot)
);

CREATE TABLE IF NOT EXISTS experiment_action_costs (
    run_id UUID NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    request_id UUID NOT NULL,
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    action TEXT NOT NULL,
    credits BIGINT NOT NULL CHECK (credits >= 0),
    ledger_transaction_id UUID REFERENCES compute_transactions(transaction_id) ON DELETE RESTRICT,
    charged_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, request_id)
);

CREATE INDEX IF NOT EXISTS experiment_action_costs_agent_idx
    ON experiment_action_costs (run_id, agent_id, charged_at);

CREATE TABLE IF NOT EXISTS experiment_snapshots (
    snapshot_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    captured_at TIMESTAMPTZ NOT NULL,
    metrics JSONB NOT NULL,
    UNIQUE (run_id, cycle)
);

CREATE INDEX IF NOT EXISTS experiment_snapshots_run_idx
    ON experiment_snapshots (run_id, cycle);
