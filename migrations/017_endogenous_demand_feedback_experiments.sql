ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 110);

CREATE TABLE IF NOT EXISTS endogenous_demand_observations (
    run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    regime INTEGER NOT NULL CHECK (regime >= 0),
    baseline_domain_index INTEGER NOT NULL CHECK (baseline_domain_index >= 0),
    generated_domain_index INTEGER NOT NULL CHECK (generated_domain_index >= 0),
    feedback_strength DOUBLE PRECISION NOT NULL CHECK (feedback_strength >= 0 AND feedback_strength <= 1),
    controller_mode TEXT NOT NULL,
    rolling_success_counts JSONB NOT NULL,
    feedback_branch_taken BOOLEAN NOT NULL,
    feedback_probability DOUBLE PRECISION NOT NULL CHECK (feedback_probability >= 0 AND feedback_probability <= 1),
    generation_probability DOUBLE PRECISION NOT NULL CHECK (generation_probability >= 0 AND generation_probability <= 1),
    generated_domain_source TEXT NOT NULL,
    winner_slot INTEGER NOT NULL CHECK (winner_slot >= 0),
    winner_agent_id UUID NOT NULL,
    success BOOLEAN NOT NULL,
    post_state_fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, cycle)
);

CREATE INDEX IF NOT EXISTS endogenous_demand_observations_run_idx
    ON endogenous_demand_observations(run_id, cycle);
CREATE INDEX IF NOT EXISTS endogenous_demand_observations_generated_idx
    ON endogenous_demand_observations(run_id, generated_domain_index, cycle);

DROP TRIGGER IF EXISTS endogenous_demand_observations_append_only
    ON endogenous_demand_observations;
CREATE TRIGGER endogenous_demand_observations_append_only
BEFORE UPDATE OR DELETE ON endogenous_demand_observations
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
