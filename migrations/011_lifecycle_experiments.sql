ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 74);

CREATE TABLE IF NOT EXISTS lifecycle_events (
    run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    slot INTEGER NOT NULL CHECK (slot >= 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    event_type TEXT NOT NULL CHECK (
        event_type IN ('fixed', 'stochastic', 'retirement', 'death', 'advisor')
    ),
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    successor_agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, cycle, slot)
);

CREATE INDEX IF NOT EXISTS lifecycle_events_run_idx
    ON lifecycle_events(run_id, cycle);

DROP TRIGGER IF EXISTS lifecycle_events_append_only ON lifecycle_events;
CREATE TRIGGER lifecycle_events_append_only
BEFORE UPDATE OR DELETE ON lifecycle_events
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
