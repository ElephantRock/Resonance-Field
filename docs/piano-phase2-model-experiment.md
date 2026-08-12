# PIANO Phase 2 — Model-backed one-agent experiment

Status: **implementation ready; scientific campaign not yet run**

This experiment tests whether two information links improve one-agent behavioral coherence:

1. broadcasting one controller intention into speech and action generation; and
2. exposing the grounded execution acknowledgement to the post-action report.

The production `AgentRuntime` remains unchanged. This module composes around the existing Phase-1 `PianoAgentRuntime` and therefore preserves Field ownership of retrieval, policy gating, execution, side effects, and decision tracing.

## Provider boundary

Resonance Field intentionally does not add an LLM/provider SDK for this experiment. `ModelBackend` is a provider-neutral protocol supplied by the runner. A backend must return:

- structured payload fields requested by each stage;
- an immutable model snapshot identifier;
- input/output token counts; and
- per-call latency.

If the returned model snapshot differs from the preregistered `required_model_snapshot`, execution fails closed.

## Equal-call intervention

Every step uses exactly four model calls in both arms:

1. `intention`
2. `speech`
3. `action`
4. `post_action_report`

Both arms receive the same observation, retrieval state, action vocabulary, trial seed, and maximum output tokens per call.

The only preregistered information-flow differences are:

| Stage | Control | Treatment |
|---|---|---|
| intention | generated | generated |
| speech | context only | context + shared intention |
| action | context only | context + shared intention |
| post-action report | proposal only | proposal + execution acknowledgement |

The control post-action call is intentionally made after execution but its prompt omits execution results. This keeps call count and scheduling comparable while isolating access to acknowledgement information.

## Frozen action vocabulary

Phase 2 defaults to:

- `OBSERVE`
- `REQUEST_TOOL`
- `SLEEP`

A run may freeze a narrower subset, but both paired arms must use the same subset. Model output outside the frozen vocabulary is rejected.

## World record

Each step exports `resonance-field-piano-phase2-step-v0.1` with:

- arm and trial seed;
- exact model snapshot;
- the existing audited Phase-1 PIANO record;
- post-action report text;
- structured `post_action_claims_success`;
- model call count, token usage, and model latency.

Raw provider credentials and provider-private state are never part of this contract.

## Scientific gate

Unit tests and deterministic fake backends validate plumbing only. They are not scientific evidence.

A result becomes eligible for scientific interpretation only when Resonance World verifies the preregistered campaign is complete, all pairs use the same frozen Field revision/model snapshot/scenario inputs, all records satisfy the four-call budget, and the preregistered analysis is applied without metric changes after observation.
