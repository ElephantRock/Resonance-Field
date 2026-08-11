ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 98);

CREATE TABLE IF NOT EXISTS matching_objective_observations (
    run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    task_id UUID NOT NULL REFERENCES market_tasks(task_id) ON DELETE CASCADE,
    bid_id UUID NOT NULL REFERENCES market_bids(bid_id) ON DELETE CASCADE,
    bidder_slot INTEGER NOT NULL CHECK (bidder_slot >= 0),
    baseline_score DOUBLE PRECISION NOT NULL,
    objective_score DOUBLE PRECISION NOT NULL,
    selected BOOLEAN NOT NULL,
    baseline_counterfactual_selected BOOLEAN NOT NULL,
    objective_counterfactual_selected BOOLEAN NOT NULL,
    objective_mode TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, cycle, bid_id)
);

CREATE INDEX IF NOT EXISTS matching_objective_observations_run_idx
    ON matching_objective_observations(run_id, cycle);
CREATE INDEX IF NOT EXISTS matching_objective_observations_task_idx
    ON matching_objective_observations(run_id, task_id);

DROP TRIGGER IF EXISTS matching_objective_observations_append_only
    ON matching_objective_observations;
CREATE TRIGGER matching_objective_observations_append_only
BEFORE UPDATE OR DELETE ON matching_objective_observations
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
