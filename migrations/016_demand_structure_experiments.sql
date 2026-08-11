ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 104);

CREATE TABLE IF NOT EXISTS demand_schedule_observations (
    run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    source_cycle INTEGER NOT NULL CHECK (source_cycle >= 0),
    regime INTEGER NOT NULL CHECK (regime >= 0),
    task_id UUID NOT NULL REFERENCES market_tasks(task_id) ON DELETE CASCADE,
    task_domain TEXT NOT NULL,
    required_skill TEXT NOT NULL,
    requester_slot INTEGER NOT NULL CHECK (requester_slot >= 0),
    candidate_slots JSONB NOT NULL,
    packet_fingerprint TEXT NOT NULL,
    schedule_mode TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, cycle)
);

CREATE INDEX IF NOT EXISTS demand_schedule_observations_run_idx
    ON demand_schedule_observations(run_id, cycle);
CREATE INDEX IF NOT EXISTS demand_schedule_observations_source_idx
    ON demand_schedule_observations(run_id, source_cycle);

DROP TRIGGER IF EXISTS demand_schedule_observations_append_only
    ON demand_schedule_observations;
CREATE TRIGGER demand_schedule_observations_append_only
BEFORE UPDATE OR DELETE ON demand_schedule_observations
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
