ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 92);

CREATE TABLE IF NOT EXISTS topology_opportunity_observations (
    run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    regime INTEGER NOT NULL CHECK (regime >= 0),
    domain_index INTEGER NOT NULL CHECK (domain_index >= 0),
    candidate_slot INTEGER NOT NULL CHECK (candidate_slot >= 0),
    candidate_rank INTEGER NOT NULL CHECK (candidate_rank >= 0),
    routing_mode TEXT NOT NULL,
    structured BOOLEAN NOT NULL,
    prior_incumbent BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, cycle, candidate_slot)
);

CREATE INDEX IF NOT EXISTS topology_opportunity_observations_run_idx
    ON topology_opportunity_observations(run_id, cycle);
CREATE INDEX IF NOT EXISTS topology_opportunity_observations_domain_idx
    ON topology_opportunity_observations(run_id, domain_index, candidate_slot);

DROP TRIGGER IF EXISTS topology_opportunity_observations_append_only
    ON topology_opportunity_observations;
CREATE TRIGGER topology_opportunity_observations_append_only
BEFORE UPDATE OR DELETE ON topology_opportunity_observations
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
