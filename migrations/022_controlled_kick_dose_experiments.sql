ALTER TABLE integration_campaign_runs
    DROP CONSTRAINT IF EXISTS integration_campaign_runs_experiment_number_check;

ALTER TABLE integration_campaign_runs
    ADD CONSTRAINT integration_campaign_runs_experiment_number_check
    CHECK (experiment_number BETWEEN 14 AND 137);

CREATE TABLE IF NOT EXISTS controlled_kick_dose_observations (
    run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 135 AND 137),
    seed INTEGER NOT NULL,
    dose INTEGER NOT NULL CHECK (dose IN (1, 2, 4)),
    scheduled_cycles JSONB NOT NULL,
    cycle INTEGER NOT NULL CHECK (cycle BETWEEN 36 AND 39),
    natural_winner_slot INTEGER NOT NULL CHECK (natural_winner_slot >= 0),
    target_slot INTEGER NOT NULL CHECK (target_slot >= 0),
    natural_radius DOUBLE PRECISION NOT NULL CHECK (natural_radius >= 0),
    requested_radius DOUBLE PRECISION NOT NULL CHECK (requested_radius > 0),
    placed_radius DOUBLE PRECISION NOT NULL CHECK (placed_radius >= 0),
    margin_delta DOUBLE PRECISION NOT NULL,
    probe_delta DOUBLE PRECISION NOT NULL,
    margin_only_winner_slot INTEGER NOT NULL CHECK (margin_only_winner_slot >= 0),
    predicted_winner_slot INTEGER NOT NULL CHECK (predicted_winner_slot >= 0),
    awarded_winner_slot INTEGER NOT NULL CHECK (awarded_winner_slot >= 0),
    margin_only_preserved BOOLEAN NOT NULL,
    probe_crossed BOOLEAN NOT NULL,
    audit JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, cycle)
);

CREATE INDEX IF NOT EXISTS controlled_kick_dose_observations_exp_seed_idx
    ON controlled_kick_dose_observations(experiment_number, seed, dose, cycle);

DROP TRIGGER IF EXISTS controlled_kick_dose_observations_append_only
    ON controlled_kick_dose_observations;
CREATE TRIGGER controlled_kick_dose_observations_append_only
BEFORE UPDATE OR DELETE ON controlled_kick_dose_observations
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();

CREATE TABLE IF NOT EXISTS controlled_kick_dose_pair_summaries (
    experiment_number INTEGER NOT NULL CHECK (experiment_number BETWEEN 135 AND 137),
    seed INTEGER NOT NULL,
    dose INTEGER NOT NULL CHECK (dose IN (1, 2, 4)),
    control_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    kick_run_id UUID NOT NULL REFERENCES integration_campaign_runs(run_id) ON DELETE CASCADE,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (experiment_number, seed, dose)
);

DROP TRIGGER IF EXISTS controlled_kick_dose_pair_summaries_append_only
    ON controlled_kick_dose_pair_summaries;
CREATE TRIGGER controlled_kick_dose_pair_summaries_append_only
BEFORE UPDATE OR DELETE ON controlled_kick_dose_pair_summaries
FOR EACH ROW EXECUTE FUNCTION reject_integration_campaign_evidence_mutation();
