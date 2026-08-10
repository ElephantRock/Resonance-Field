CREATE TABLE IF NOT EXISTS market_auction_scores (
    auction_score_id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES market_tasks(task_id) ON DELETE CASCADE,
    bid_id UUID NOT NULL REFERENCES market_bids(bid_id) ON DELETE CASCADE,
    bidder_agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    baseline_score DOUBLE PRECISION NOT NULL,
    signal_adjustment DOUBLE PRECISION NOT NULL,
    total_score DOUBLE PRECISION NOT NULL,
    provider_label TEXT NOT NULL,
    components JSONB NOT NULL DEFAULT '{}'::jsonb,
    selected BOOLEAN NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, bid_id)
);

CREATE INDEX IF NOT EXISTS market_auction_scores_task_idx
    ON market_auction_scores(task_id, total_score DESC);

CREATE OR REPLACE FUNCTION reject_market_auction_score_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'market auction score provenance is append-only';
END;
$$;

DROP TRIGGER IF EXISTS market_auction_scores_append_only ON market_auction_scores;
CREATE TRIGGER market_auction_scores_append_only
BEFORE UPDATE OR DELETE ON market_auction_scores
FOR EACH ROW EXECUTE FUNCTION reject_market_auction_score_mutation();
