ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 122);

CREATE TABLE IF NOT EXISTS trajectory_hysteresis_states (
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 117 AND 122),
    cohort TEXT NOT NULL,
    history_kind TEXT NOT NULL CHECK (
        history_kind IN ('smooth_reference', 'aligned_history', 'counter_history', 'annealed_history')
    ),
    seed INTEGER NOT NULL,
    activation_cycle INTEGER NOT NULL CHECK (activation_cycle > 0),
    control_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    treatment_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    endpoint_features JSONB NOT NULL,
    trajectory_observables JSONB NOT NULL,
    preactivation_exact BOOLEAN NOT NULL,
    trajectory_exact BOOLEAN NOT NULL,
    control_post_incumbency DOUBLE PRECISION,
    treatment_post_incumbency DOUBLE PRECISION,
    delta_incumbency DOUBLE PRECISION,
    success_effect DOUBLE PRECISION,
    knowledge_effect DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (experiment_number, cohort, history_kind, seed)
);

CREATE INDEX IF NOT EXISTS trajectory_hysteresis_states_cohort_idx
    ON trajectory_hysteresis_states(experiment_number, cohort, history_kind, seed);

DROP TRIGGER IF EXISTS trajectory_hysteresis_states_append_only
    ON trajectory_hysteresis_states;
CREATE TRIGGER trajectory_hysteresis_states_append_only
BEFORE UPDATE OR DELETE ON trajectory_hysteresis_states
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
