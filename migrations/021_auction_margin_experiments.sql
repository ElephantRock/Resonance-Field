ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 134);

CREATE TABLE IF NOT EXISTS auction_margin_observations (
    run_id UUID PRIMARY KEY REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 129 AND 134),
    cohort TEXT NOT NULL,
    arm_label TEXT NOT NULL,
    seed INTEGER NOT NULL,
    activation_cycle INTEGER NOT NULL CHECK (activation_cycle >= 0),
    natural_winner_slot INTEGER NOT NULL CHECK (natural_winner_slot >= 0),
    target_slot INTEGER NOT NULL CHECK (target_slot >= 0),
    natural_radius DOUBLE PRECISION NOT NULL CHECK (natural_radius >= 0),
    requested_radius DOUBLE PRECISION CHECK (requested_radius > 0),
    placed_radius DOUBLE PRECISION NOT NULL CHECK (placed_radius >= 0),
    margin_delta DOUBLE PRECISION NOT NULL,
    probe_delta DOUBLE PRECISION NOT NULL CHECK (probe_delta >= 0),
    margin_only_winner_slot INTEGER NOT NULL CHECK (margin_only_winner_slot >= 0),
    predicted_winner_slot INTEGER NOT NULL CHECK (predicted_winner_slot >= 0),
    awarded_winner_slot INTEGER NOT NULL CHECK (awarded_winner_slot >= 0),
    margin_only_preserved BOOLEAN NOT NULL,
    probe_crossed BOOLEAN NOT NULL,
    audit JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS auction_margin_observations_lookup_idx
    ON auction_margin_observations(experiment_number, cohort, seed, arm_label);

DROP TRIGGER IF EXISTS auction_margin_observations_append_only ON auction_margin_observations;
CREATE TRIGGER auction_margin_observations_append_only
BEFORE UPDATE OR DELETE ON auction_margin_observations
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();

CREATE TABLE IF NOT EXISTS auction_margin_pair_summaries (
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 130 AND 134),
    cohort TEXT NOT NULL,
    seed INTEGER NOT NULL,
    near_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    buffered_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (experiment_number, cohort, seed)
);

DROP TRIGGER IF EXISTS auction_margin_pair_summaries_append_only ON auction_margin_pair_summaries;
CREATE TRIGGER auction_margin_pair_summaries_append_only
BEFORE UPDATE OR DELETE ON auction_margin_pair_summaries
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
