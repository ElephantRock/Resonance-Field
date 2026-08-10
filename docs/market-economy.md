# Compute Economy and Task Market v0.1

This slice introduces the first explicit selection pressure in Resonance Field: persistent agent identities compete for bounded compute credits through a sealed-bid task market.

## Separation of concerns

Reputation is not money. v0.1 stores compute credits independently of any future reputation genome. Credits are scarce and transferable; reputation will later estimate evidence-backed capability.

Agents cannot issue credits. Credit allocation is a trusted control-plane operation implemented as a treasury transfer and is not exposed as an `ActionType` executor.

## Persistent agent identity

`agents` stores:

- `agent_id`
- generation
- lifecycle status
- model profile
- creation time
- last-active time

Each registered agent receives exactly one `agent` compute account.

## Double-entry credits

The compute economy uses:

```text
compute_accounts
compute_transactions
compute_postings
```

Every transfer creates one immutable transaction with two postings:

```text
source account   -N
recipient account +N
-------------------
net               0
```

A deferred PostgreSQL constraint verifies that every transaction sums to zero before commit. Ledger transactions and postings reject `UPDATE` and `DELETE` operations.

A fixed treasury account holds the initial v0.1 credit supply. Administrative allocation transfers credits from treasury to an agent; it does not mint them inside the agent economy.

## Task escrow

`POST_TASK` creates a dedicated `task_escrow` account and moves the full task budget from the requester into that account atomically.

Consequences:

- an agent cannot post work it cannot fund;
- a task budget cannot be double-spent while the task is open;
- winner settlement and requester refunds are ordinary auditable ledger transfers;
- failure during task creation rolls back both the task and escrow movement.

When the PostgreSQL agent runtime executes a market action, the market mutation and its `DecisionEvent` share one outer transaction. Market service transactions become nested savepoints. If decision-provenance persistence fails, the market task, escrow account, and credit transfer roll back together rather than leaving an orphaned side effect.

This atomic guarantee requires the PostgreSQL event store, market service, economy repository, and substrate repository participating in a runtime step to share the same connection.

## Sealed bids

`BID_TASK` records:

- bidder
- price
- confidence
- estimated completion time
- strategy summary
- submission time

A bidder may submit at most one bid per task. Requesters cannot bid on their own tasks. Bids above the escrowed budget are rejected.

Submitted bids are sealed from the agent-facing service contract: there is no public bid-listing method. At the database layer, price, confidence, timing, bidder identity, and strategy are immutable after submission. Resolution may change only `status` from `sealed` to `selected` or `rejected`.

The bidding interval is half-open: a bid is valid only while `submitted_at < deadline`. At the exact deadline, bidding is closed and `award()` is permitted. This removes order-dependent behavior at the boundary.

## Auction scoring

The v0.1 auction intentionally does not invent a reputation signal before reputation exists.

Eligible bids are scored as:

```text
0.45 * confidence
+ 0.35 * price_efficiency
+ 0.20 * completion_speed
```

where:

```text
price_efficiency = 1 - price / budget
completion_speed = 1 - min(1, estimated_completion / task_window)
```

Ties resolve deterministically by submission time and bid ID.

A future reputation slice may add evidence-backed capability terms. Until then, keeping the score observable and falsifiable is preferable to a placeholder trust number.

## Award and settlement

At or after the bidding deadline:

1. the market controller ranks sealed eligible bids;
2. the winning bid becomes `selected` in storage and in the returned `AuctionResult`;
3. remaining bids become `rejected`;
4. the task becomes `awarded`;
5. after an external completion/evaluation signal, `settle()` pays the winner from escrow;
6. unused budget returns to the requester;
7. the task becomes `completed`.

If a task receives no bids, the full escrow balance returns to the requester and the task becomes `cancelled`.

Award and settlement are controller operations, not agent action primitives. This prevents a bidder from self-awarding or self-settling work.

## Agent runtime integration

The default policy gateway now permits:

```text
POST_TASK
BID_TASK
```

Both still pass through the same sequence as every other action:

```text
OBSERVE -> QUERY -> CHOOSE -> POLICY GATE -> ACT -> TRACE
```

The runtime can execute these actions only when a `MarketService` is configured. Missing market infrastructure produces a traced execution failure rather than an ungoverned fallback.

For PostgreSQL-backed runs, `ACT -> TRACE` is a transactional unit of work: the runtime opens the event-store transaction, executes the side effect, appends the decision event, and commits only after both succeed.

## Research consequence

The system can now measure market behavior without assigning occupational roles. Useful future behavioral features include:

- tasks posted;
- bid frequency;
- bid price relative to budget;
- confidence calibration;
- completion-time estimates;
- win rate;
- earned credits;
- delegated versus self-executed work;
- recurring requester/bidder relationships.

These signals can feed the role-emergence and interaction-network metrics without pre-labeling agents as specialists.
