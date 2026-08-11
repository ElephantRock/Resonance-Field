ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 116);

CREATE TABLE IF NOT EXISTS phase_observability_states (
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 111 AND 116),
    cohort TEXT NOT NULL,
    seed INTEGER NOT NULL,
    activation_cycle INTEGER NOT NULL CHECK (activation_cycle > 0),
    control_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    treatment_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    state_features JSONB NOT NULL,
    preactivation_exact BOOLEAN NOT NULL,
    control_post_incumbency DOUBLE PRECISION,
    treatment_post_incumbency DOUBLE PRECISION,
    delta_incumbency DOUBLE PRECISION,
    success_effect DOUBLE PRECISION,
    knowledge_effect DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (experiment_number, seed)
);

CREATE INDEX IF NOT EXISTS phase_observability_states_cohort_idx
    ON phase_observability_states(experiment_number, cohort, seed);

DROP TRIGGER IF EXISTS phase_observability_states_append_only
    ON phase_observability_states;
CREATE TRIGGER phase_observability_states_append_only
BEFORE UPDATE OR DELETE ON phase_observability_states
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
