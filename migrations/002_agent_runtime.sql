CREATE TABLE IF NOT EXISTS decision_events (
    event_id UUID PRIMARY KEY,
    agent_id UUID NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    trigger TEXT NOT NULL,
    proposed_action TEXT NOT NULL,
    policy_result TEXT NOT NULL,
    policy_reason TEXT NOT NULL,
    outcome_status TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    request_id UUID NOT NULL,
    correlation_id UUID NOT NULL,
    retrieved_trace_ids UUID[] NOT NULL DEFAULT '{}',
    output_trace_ids UUID[] NOT NULL DEFAULT '{}',
    action_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS decision_events_agent_time_idx
    ON decision_events (agent_id, occurred_at DESC, event_id);
CREATE INDEX IF NOT EXISTS decision_events_correlation_idx
    ON decision_events (correlation_id);

CREATE OR REPLACE FUNCTION reject_decision_event_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'decision_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS decision_events_append_only ON decision_events;
CREATE TRIGGER decision_events_append_only
BEFORE UPDATE OR DELETE ON decision_events
FOR EACH ROW EXECUTE FUNCTION reject_decision_event_mutation();
