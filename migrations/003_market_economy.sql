CREATE TABLE IF NOT EXISTS agents (
    agent_id UUID PRIMARY KEY,
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    status TEXT NOT NULL DEFAULT 'active',
    model_profile TEXT NOT NULL DEFAULT 'STANDARD',
    created_at TIMESTAMPTZ NOT NULL,
    last_active_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS compute_accounts (
    account_id UUID PRIMARY KEY,
    owner_agent_id UUID UNIQUE REFERENCES agents(agent_id) ON DELETE RESTRICT,
    account_kind TEXT NOT NULL,
    reference_id UUID,
    balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS compute_accounts_reference_idx
    ON compute_accounts (account_kind, reference_id)
    WHERE reference_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS compute_transactions (
    transaction_id UUID PRIMARY KEY,
    reason TEXT NOT NULL,
    reference_type TEXT,
    reference_id UUID,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS compute_postings (
    transaction_id UUID NOT NULL REFERENCES compute_transactions(transaction_id) ON DELETE RESTRICT,
    account_id UUID NOT NULL REFERENCES compute_accounts(account_id) ON DELETE RESTRICT,
    amount BIGINT NOT NULL CHECK (amount <> 0),
    PRIMARY KEY (transaction_id, account_id)
);

CREATE OR REPLACE FUNCTION reject_compute_ledger_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'compute ledger is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS compute_transactions_append_only ON compute_transactions;
CREATE TRIGGER compute_transactions_append_only
BEFORE UPDATE OR DELETE ON compute_transactions
FOR EACH ROW EXECUTE FUNCTION reject_compute_ledger_mutation();

DROP TRIGGER IF EXISTS compute_postings_append_only ON compute_postings;
CREATE TRIGGER compute_postings_append_only
BEFORE UPDATE OR DELETE ON compute_postings
FOR EACH ROW EXECUTE FUNCTION reject_compute_ledger_mutation();

CREATE OR REPLACE FUNCTION enforce_balanced_compute_transaction()
RETURNS trigger AS $$
DECLARE
    posting_sum BIGINT;
BEGIN
    SELECT COALESCE(SUM(amount), 0)
      INTO posting_sum
      FROM compute_postings
     WHERE transaction_id = NEW.transaction_id;
    IF posting_sum <> 0 THEN
        RAISE EXCEPTION 'compute transaction % is not balanced: %', NEW.transaction_id, posting_sum;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS compute_transaction_balanced ON compute_postings;
CREATE CONSTRAINT TRIGGER compute_transaction_balanced
AFTER INSERT ON compute_postings
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_balanced_compute_transaction();

INSERT INTO compute_accounts (
    account_id, owner_agent_id, account_kind, reference_id, balance, created_at
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    NULL,
    'treasury',
    NULL,
    1000000000000,
    '2026-01-01T00:00:00+00:00'
)
ON CONFLICT (account_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS market_tasks (
    task_id UUID PRIMARY KEY,
    requester_agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    escrow_account_id UUID NOT NULL UNIQUE REFERENCES compute_accounts(account_id) ON DELETE RESTRICT,
    description TEXT NOT NULL,
    budget BIGINT NOT NULL CHECK (budget > 0),
    deadline TIMESTAMPTZ NOT NULL,
    required_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    success_condition JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    awarded_agent_id UUID REFERENCES agents(agent_id) ON DELETE RESTRICT,
    winning_bid_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    awarded_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS market_tasks_status_deadline_idx
    ON market_tasks (status, deadline, created_at);

CREATE TABLE IF NOT EXISTS market_bids (
    bid_id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES market_tasks(task_id) ON DELETE RESTRICT,
    bidder_agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    price BIGINT NOT NULL CHECK (price > 0),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    estimated_completion_seconds INTEGER NOT NULL CHECK (estimated_completion_seconds > 0),
    strategy_summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sealed',
    submitted_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, bidder_agent_id)
);

ALTER TABLE market_tasks
    DROP CONSTRAINT IF EXISTS market_tasks_winning_bid_fk;
ALTER TABLE market_tasks
    ADD CONSTRAINT market_tasks_winning_bid_fk
    FOREIGN KEY (winning_bid_id) REFERENCES market_bids(bid_id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS market_bids_task_idx
    ON market_bids (task_id, submitted_at, bid_id);

CREATE OR REPLACE FUNCTION reject_market_bid_mutation()
RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'sealed' AND NEW.status <> OLD.status THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'sealed market bids are immutable';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS market_bids_immutable ON market_bids;
CREATE TRIGGER market_bids_immutable
BEFORE UPDATE OR DELETE ON market_bids
FOR EACH ROW EXECUTE FUNCTION reject_market_bid_mutation();
