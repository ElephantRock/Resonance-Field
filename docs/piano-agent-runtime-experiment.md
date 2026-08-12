# PIANO agent-runtime experiment

This branch adds a narrow experimental contract for Project Sid / PIANO-inspired coherence studies without changing the production `AgentRuntime` execution path.

## Ownership boundary

Resonance Field continues to own:

- substrate retrieval;
- agent-local policy execution;
- action proposals;
- policy gating;
- side effects;
- decision-event tracing; and
- execution outcomes.

Resonance World may orchestrate paired experimental arms and consume the exported experimental record, but it must not reconstruct hidden Field cognitive state or execute Field actions itself.

## Contract

A `PianoPolicy` returns one `PianoProposal` containing:

1. `intention` — the high-level intended behavior;
2. `speech` — an independently observable language proposal, or `None`;
3. `action` — the normal Field `ActionRequest` that is passed unchanged into production `AgentRuntime`;
4. `expected_outcome_status` — optional predicted execution status; and
5. `expected_effects` — optional expected outcome data used for acknowledgement checks.

`PianoAgentRuntime.step()` returns the original proposal, Field's normal `StepResult`, and an `ExecutionAcknowledgement` derived only after the production runtime has gated and executed the action.

The World export record uses `DecisionEvent.action_payload`, not the raw `ActionRequest.payload`, so Field's existing audit redaction rules remain authoritative at the boundary.

## What this does not implement

This adapter does not yet claim to implement PIANO's parallel cognitive scheduler. The current production `AgentRuntime` is synchronous, and this experiment preserves that boundary. A policy may internally compute proposal channels concurrently, but the adapter captures one atomic proposal per runtime step.

The purpose of this branch is to make the first live paired experiment scientifically measurable before introducing a larger scheduler change.

## Phase 1 gate

The first live experiment should run the same one-agent scenario under two policies:

- **control:** independent speech/action generation without a shared high-level intention constraint;
- **treatment:** speech and action generation conditioned on a shared intention plus explicit expected execution state.

Both arms must use the same Field revision, observation sequence, action vocabulary, gateway policy, substrate state, model/tool budget, and random seeds where applicable.

Primary measurements belong in Resonance World:

- cross-channel contradiction rate;
- intention/action divergence;
- unsupported success-claim rate;
- action grounding failures; and
- latency / compute overhead.

No multi-agent scale-up should occur until the one-agent paired protocol produces reproducible records and the measurement code is frozen.
