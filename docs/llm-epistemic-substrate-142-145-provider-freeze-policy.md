# Experiments 142–145 — Provider and Model Identity Freeze Policy

Date: 2026-08-12
Status: pre-confirmatory; no confirmatory content created or accessed

## Objective

Define how the stochastic provider/model is identified and frozen before the 512-case confirmatory corpus is created.

The policy distinguishes the **requested model string** from the **provider-returned model identity**. Successful instrumentation requested `glm-5.1` but reported `glm-5.2` in completion metadata. The confirmatory seal must therefore not assume that the request alias alone identifies the model that actually served a completion.

## Frozen request surface

The confirmatory provider request contract is based on the successfully exercised instrumentation surface:

- provider: Z.AI;
- protocol: OpenAI-compatible Chat Completions;
- Coding endpoint: `https://api.z.ai/api/coding/paas/v4`;
- requested model string: `glm-5.1`;
- temperature: `1.0`;
- thinking: enabled;
- `clear_thinking: false` where sent by the compatibility surface;
- JSON object response format for structured producer/final evaluator responses;
- producer maximum output: 12,000 tokens;
- evaluator maximum output: 6,000 tokens;
- producer structured-schema retries: at most 2 after the first attempt;
- evaluator structured-schema retries: at most 2 after the first attempt;
- evaluator factual retrieval: 12 units/call, 24 units/answer, 8 tool rounds;
- SDK-internal HTTP retries: disabled;
- explicit transient Z.AI retries: business codes 1302/1305 only, at most 5 retries, exponential delays 2/4/8/16/32 seconds;
- quota/subscription/policy and non-transient failures: fail closed.

No live web, provider search tool, browsing tool, or raw corpus access is exposed to the evaluator.

## Why the requested model remains `glm-5.1`

Current official Z.AI documentation explicitly documents `glm-5.1` on the OpenAI-compatible API and Coding endpoint and documents the relevant thinking/function-call/structured-output capabilities. The campaign therefore retains the documented request alias instead of changing it to the provider-returned `glm-5.2` string merely because instrumentation metadata reported that backend identity.

This choice is protocol stability, not model selection based on treatment outcomes.

## Synthetic pre-seal identity probe

Before any confirmatory case content is created, run exactly one synthetic compatibility probe on the frozen provider surface.

The probe contains no scientific corpus text and executes no P/S/G/R substrate treatment. It makes three small calls:

1. structured JSON response;
2. forced synthetic function call;
3. tool-free structured finalization after the synthetic tool result.

All three calls request `glm-5.1`. The probe records the exact `completion.model` returned by the provider for each call.

The probe passes only if:

- all three request-surface checks succeed;
- every response includes a non-empty model identity; and
- all three returned model identities are byte-identical.

Implementation:

- `scripts/probe_llm_epistemic_zai_identity.py`
- `.github/workflows/llm-epistemic-substrate-142-145-provider-identity-probe.yml`

The probe output and SHA-256 are retained as pre-seal evidence.

## Sealed returned-model identity

The exact consistent provider-returned identity from the successful synthetic probe becomes the **sealed expected response model** for the confirmatory execution.

The seal records separately:

- requested model string: `glm-5.1`;
- expected provider-returned model identity: value from the successful probe;
- provider endpoint;
- probe artifact digest;
- probe request-contract digest;
- code SHA implementing the request/identity checks.

No model identity is inferred from marketing names or request aliases after sealing.

## Fail-closed execution enforcement

Confirmatory transport must wrap every completion call with exact returned-identity enforcement.

The check applies to:

- producer initial responses;
- producer schema retries;
- evaluator tool-call responses;
- evaluator boundary-finalization responses;
- evaluator schema retries;
- every independent evaluator draw.

If any completion returns an identity different from the sealed expected identity—or omits identity—the confirmatory execution stops as a **provider identity failure**. It is not scored as a case failure and does not authorize model substitution, case replacement, or continuation on a mixed-model cohort.

Implementation support: `ModelIdentityEnforcingCompletions` in `src/resonance/experiments/llm_epistemic_zai_retry.py`.

## Identity drift before corpus creation

If the synthetic probe fails or returns inconsistent identities **before confirmatory corpus creation**, the campaign remains blocked at pre-seal status. A provider/model protocol revision is permitted only if:

- it is documented before any confirmatory content exists;
- the same synthetic compatibility probe is rerun on the revised surface; and
- no instrumentation treatment outcome is used to select between provider/model alternatives.

## Identity drift after seal

After the confirmatory manifest/model seal exists, a returned-model mismatch is not repairable by silently accepting the new identity. The run is inadmissible under the existing seal.

A new model would require a new preregistered replication campaign or a formally new seal created without access to outcomes from the invalid mixed/drifted execution. The current campaign may not pool identities.

## Conversation/state policy

Provider requests are stateless across cases and evaluator draws except for the explicit message history constructed inside one evaluator draw. No provider conversation ID or server-side thread is reused across cases/arms.

Within one evaluator draw, assistant/tool messages are replayed explicitly to support tool use. Reasoning content returned by the provider may be carried only within that same draw when required by the compatibility protocol. It is never deposited into the epistemic substrate, shared across arms, or reused across cases.

Producer calls are independent per assigned producer task; no producer conversation is reused.

## Remaining provider freeze action

The policy is frozen, but the exact **served identity value** is not frozen until the one-shot synthetic probe completes successfully. No confirmatory corpus may be created before that artifact is recorded and referenced by the seal-preparation record.
