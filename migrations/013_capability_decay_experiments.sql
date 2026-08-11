ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 86);

CREATE TABLE IF NOT EXISTS capability_practice_observations (
    run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    skill TEXT NOT NULL,
    candidate_slot INTEGER NOT NULL CHECK (candidate_slot >= 0),
    selected BOOLEAN NOT NULL,
    cumulative_practice INTEGER NOT NULL CHECK (cumulative_practice >= 0),
    effective_practice DOUBLE PRECISION NOT NULL CHECK (effective_practice >= 0),
    inactivity_cycles INTEGER NOT NULL CHECK (inactivity_cycles >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, cycle, agent_id, skill)
);

CREATE INDEX IF NOT EXISTS capability_practice_observations_run_idx
    ON capability_practice_observations(run_id, cycle);

DROP TRIGGER IF EXISTS capability_practice_observations_append_only
    ON capability_practice_observations;
CREATE TRIGGER capability_practice_observations_append_only
BEFORE UPDATE OR DELETE ON capability_practice_observations
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
