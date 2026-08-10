# Agent Runtime v0.1

The v0.1 agent runtime establishes the smallest executable control loop shared by all initially general-purpose agents.

## Execution sequence

```text
OBSERVE -> QUERY SUBSTRATE -> CHOOSE -> POLICY GATE -> ACT -> TRACE
```

1. An `AgentObservation` supplies a trigger, timestamp, and query embedding.
2. The runtime queries the shared substrate before the agent policy selects an action.
3. The `AgentPolicy` returns a typed `ActionRequest`; it does not execute side effects.
4. The `PolicyGateway` allows, rejects, or marks the request as requiring human approval.
5. Only allowed requests reach the v0.1 executor.
6. Every proposal produces an append-only `DecisionEvent`, including rejected and failed actions.

## Common primitive vocabulary

All agents share the same action vocabulary:

- `OBSERVE`
- `QUERY_SUBSTRATE`
- `READ_TRACE`
- `WRITE_TRACE`
- `REINFORCE_TRACE`
- `CHALLENGE_TRACE`
- `CROSSOVER`
- `POST_TASK`
- `BID_TASK`
- `DELEGATE`
- `REQUEST_TOOL`
- `REQUEST_FORK`
- `VOTE`
- `ABSTAIN`
- `SLEEP`

The existence of a primitive does not mean its executor is enabled. v0.1 currently enables internal observation/substrate actions, task posting and bidding through a configured market service, plus `ABSTAIN` and `SLEEP`. Tool, Oracle, delegation, challenge, crossover, and voting executors remain disabled until their dedicated policy and execution layers exist.

## Provenance boundary

`DecisionEvent` records:

- agent, request, and correlation identifiers;
- trigger and timestamp;
- retrieved trace identifiers;
- proposed action;
- policy result and reason;
- outcome status;
- output trace identifiers;
- confidence;
- audit-safe action metadata;
- audit-safe outcome metadata;
- execution error summary when applicable.

The runtime does **not** persist private chain-of-thought, raw credentials, or embedding vectors as decision provenance. Credential-like fields are redacted and explicit embeddings are summarized by dimensionality.

PostgreSQL stores decision events in `decision_events`. A database trigger rejects row updates and deletes so application provenance is append-only.

## Policy semantics

The policy gateway is deliberately separate from the agent policy. An agent may propose an action it is not authorized or equipped to execute; that proposal remains observable as a rejected decision event.

The default v0.1 gateway permits:

```text
OBSERVE
QUERY_SUBSTRATE
READ_TRACE
WRITE_TRACE
REINFORCE_TRACE
POST_TASK
BID_TASK
ABSTAIN
SLEEP
```

`POST_TASK` and `BID_TASK` still require a configured `MarketService`; otherwise the allowed proposal fails execution and the failure remains visible in provenance. This keeps authorization separate from infrastructure availability.

All other primitives are rejected until an executor and corresponding safety policy exist. Selected actions may alternatively be configured as `REQUIRE_HUMAN_APPROVAL`.

## Research consequence

No occupational role is encoded in this runtime. Behavioral roles must be inferred later from action frequencies, substrate regions, tool use, market behavior, and interaction patterns. The runtime therefore provides the event stream required by the emergence metrics without pre-labeling agents as Foragers, Critics, Synthesists, or Brokers.
