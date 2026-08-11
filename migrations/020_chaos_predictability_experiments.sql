ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 128);

CREATE TABLE IF NOT EXISTS chaos_predictability_observations (
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 123 AND 128),
    cohort TEXT NOT NULL,
    perturbation_family TEXT NOT NULL CHECK (
        perturbation_family IN ('bid_confidence', 'trace_energy', 'embedding_control', 'feedback_delay')
    ),
    epsilon DOUBLE PRECISION NOT NULL CHECK (epsilon >= 0),
    feedback_strength DOUBLE PRECISION NOT NULL CHECK (feedback_strength BETWEEN 0 AND 1),
    seed INTEGER NOT NULL,
    cycle INTEGER NOT NULL CHECK (cycle >= 0),
    baseline_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    perturbed_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    micro_distance DOUBLE PRECISION NOT NULL CHECK (micro_distance BETWEEN 0 AND 1),
    meso_distance DOUBLE PRECISION NOT NULL CHECK (meso_distance BETWEEN 0 AND 1),
    macro_distance DOUBLE PRECISION NOT NULL CHECK (macro_distance BETWEEN 0 AND 1),
    candidate_distance DOUBLE PRECISION NOT NULL CHECK (candidate_distance BETWEEN 0 AND 1),
    micro_components JSONB NOT NULL,
    meso_components JSONB NOT NULL,
    macro_components JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (
        experiment_number, cohort, perturbation_family, epsilon,
        feedback_strength, seed, cycle
    )
);

CREATE INDEX IF NOT EXISTS chaos_predictability_observations_lookup_idx
    ON chaos_predictability_observations(
        experiment_number, cohort, perturbation_family, feedback_strength, epsilon, seed, cycle
    );

DROP TRIGGER IF EXISTS chaos_predictability_observations_append_only
    ON chaos_predictability_observations;
CREATE TRIGGER chaos_predictability_observations_append_only
BEFORE UPDATE OR DELETE ON chaos_predictability_observations
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();

CREATE TABLE IF NOT EXISTS chaos_predictability_pairs (
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 123 AND 128),
    cohort TEXT NOT NULL,
    perturbation_family TEXT NOT NULL CHECK (
        perturbation_family IN ('bid_confidence', 'trace_energy', 'embedding_control', 'feedback_delay')
    ),
    epsilon DOUBLE PRECISION NOT NULL CHECK (epsilon >= 0),
    feedback_strength DOUBLE PRECISION NOT NULL CHECK (feedback_strength BETWEEN 0 AND 1),
    seed INTEGER NOT NULL,
    baseline_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    perturbed_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (
        experiment_number, cohort, perturbation_family, epsilon,
        feedback_strength, seed
    )
);

DROP TRIGGER IF EXISTS chaos_predictability_pairs_append_only
    ON chaos_predictability_pairs;
CREATE TRIGGER chaos_predictability_pairs_append_only
BEFORE UPDATE OR DELETE ON chaos_predictability_pairs
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
