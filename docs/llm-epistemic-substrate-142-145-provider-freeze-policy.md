# Experiments 142–145 — Provider and Model Identity Freeze Policy

Date: 2026-08-12
Status: provider identity freeze resolved; no confirmatory content created or accessed

## Objective

Define and freeze how the stochastic provider/model is identified before the 512-case confirmatory corpus is created.

The policy distinguishes the **requested model string** from the **provider-returned model identity**. Successful instrumentation requested `glm-5.1` but reported `glm-5.2` in completion metadata. A dedicated synthetic probe has now confirmed that separation on the frozen request surface.

## Frozen request surface

The confirmatory provider request contract is based on the successfully exercised instrumentation surface:

- provider: Z.AI;
- protocol: OpenAI-compatible Chat Completions;
- Coding endpoint: `https://api.z.ai/api/coding/paas/v4`;
- requested model string: **`glm-5.1`**;
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

## Requested alias versus served identity

The campaign retains the request alias `glm-5.1` rather than rewriting it to a backend identity observed in completion metadata. Requested identity and returned identity are separate frozen fields.

The dedicated pre-seal probe establishes the expected returned identity empirically on the actual request surface without using scientific corpus content or executing P/S/G/R treatments.

## Successful synthetic identity probe

One immutable probe was executed:

- workflow run: `31642753502`;
- trigger/head SHA: `a0bc74d8b163932e1b417dbad99122d5dcc815ee`;
- artifact ID: `9159514128`;
- artifact digest: `sha256:c56a57e94a57657054195960bb0bd556aadd504b7d6d2ba9e53a19babba4757a`;
- probe JSON SHA-256: `835bc51a029517d6d3f5271c5f0f0d98e286df79b486d64742517742c81d7581`;
- request-contract SHA-256: `739fba6b309308d0798003f7c1c6a5d9b859b8ad2c4d94fc3bdcd75a8f246acd`.

Boundary evidence from the probe:

- `inferential: false`;
- `confirmatory_access: false`;
- `confirmatory_cases_evaluated: false`;
- `treatment_execution: false`;
- `scientific_content_access: false`.

The three synthetic request modes were:

1. structured JSON response;
2. forced synthetic function call;
3. tool-free structured finalization after the synthetic tool result.

All three requested `glm-5.1`. All three returned **`glm-5.2`**.

Detailed evidence: `docs/llm-epistemic-substrate-142-145-provider-identity-probe-results.md`.

## Frozen identity pair

The pre-confirmatory provider identity pair is now:

- **requested model:** `glm-5.1`;
- **expected provider-returned model:** `glm-5.2`.

The exact endpoint, probe artifact/hash evidence, and request-contract hash are frozen in `configs/experiments/llm-epistemic-substrate-142-145.json` under protocol revision `003-provider-identity-freeze`.

## Fail-closed execution enforcement

Every confirmatory completion must be wrapped with exact returned-identity enforcement against `glm-5.2`.

The check applies to:

- producer initial responses;
- producer schema retries;
- evaluator tool-call responses;
- evaluator boundary-finalization responses;
- evaluator schema retries;
- every independent evaluator draw.

If any completion returns an identity different from `glm-5.2`, or omits identity, execution stops as a **provider identity failure**. It is not scored as a case failure and does not authorize model substitution, case replacement, or continuation on a mixed-model cohort.

Implementation support: `ModelIdentityEnforcingCompletions` in `src/resonance/experiments/llm_epistemic_zai_retry.py`.

## Identity drift before corpus creation

The required probe has passed, so the provider-identity blocker is resolved for pre-seal work.

If a future mechanical check before corpus creation reveals the frozen request surface is no longer usable, the campaign remains blocked. A provider/model protocol revision is permitted only if documented before any confirmatory content exists and without using instrumentation treatment outcomes to select among model alternatives.

## Identity drift after seal

After the confirmatory manifest/model seal exists, a returned-model mismatch is not repairable by silently accepting a new identity. The run is inadmissible under the existing seal.

A new provider/model identity would require a new preregistered replication campaign or a formally new seal created without access to outcomes from the invalid drifted execution. The current campaign may not pool model identities.

## Conversation/state policy

Provider requests are stateless across cases and evaluator draws except for explicit message history constructed inside one evaluator draw. No provider conversation ID or server-side thread is reused across cases/arms.

Within one evaluator draw, assistant/tool messages are replayed explicitly to support tool use. Reasoning content returned by the provider may be carried only within that same draw when required by the compatibility protocol. It is never deposited into the epistemic substrate, shared across arms, or reused across cases.

Producer calls are independent per assigned producer task; no producer conversation is reused.

## Current boundary

The provider/model identity freeze is resolved. Confirmatory corpus construction is still blocked by the remaining case-construction/strata, scoring/seal, and stratum-level evaluable-case policies.

No confirmatory case has been created, opened, or evaluated.
