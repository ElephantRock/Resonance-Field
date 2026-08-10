CREATE TABLE IF NOT EXISTS integration_campaign_runs (
    run_id UUID PRIMARY KEY,
    campaign_name TEXT NOT NULL,
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 14 AND 40),
    arm_label TEXT NOT NULL,
    seed INTEGER NOT NULL,
    policy JSONB NOT NULL,
    environment JSONB NOT NULL,
    metrics JSONB NOT NULL,
    invariants JSONB NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    UNIQUE (campaign_name, experiment_number, arm_label, seed)
);

CREATE TABLE IF NOT EXISTS integration_campaign_outcomes (
    run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    regime INTEGER NOT NULL CHECK (regime >= 0),
    task_id UUID NOT NULL REFERENCES market_tasks(task_id) ON DELETE CASCADE,
    task_domain TEXT NOT NULL,
    domain_index INTEGER NOT NULL CHECK (domain_index >= 0),
    required_skill TEXT NOT NULL,
    winner_agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    winner_slot INTEGER NOT NULL CHECK (winner_slot >= 0),
    success BOOLEAN NOT NULL,
    recorded_positive BOOLEAN NOT NULL,
    reputation_score DOUBLE PRECISION NOT NULL CHECK (reputation_score BETWEEN 0 AND 1),
    winning_price INTEGER NOT NULL CHECK (winning_price > 0),
    task_budget INTEGER NOT NULL CHECK (task_budget > 0),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, cycle),
    UNIQUE (task_id)
);

CREATE INDEX IF NOT EXISTS integration_campaign_outcomes_run_idx
    ON integration_campaign_outcomes(run_id, cycle);

CREATE OR REPLACE FUNCTION reject_integration_campaign_evidence_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'integration campaign evidence is append-only';
END;
$$;

DROP TRIGGER IF EXISTS integration_campaign_runs_append_only ON integration_campaign_runs;
CREATE TRIGGER integration_campaign_runs_append_only
BEFORE UPDATE OR DELETE ON integration_campaign_runs
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();

DROP TRIGGER IF EXISTS integration_campaign_outcomes_append_only ON integration_campaign_outcomes;
CREATE TRIGGER integration_campaign_outcomes_append_only
BEFORE UPDATE OR DELETE ON integration_campaign_outcomes
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
