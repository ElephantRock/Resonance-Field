# Experiments 142–145 — Provider Revision: Z.AI

Date: 2026-08-12
Status: instrumentation-only provider record

## Initial reason for revision

The original stochastic instrumentation candidate was `gpt-5.6-terra` through the OpenAI Responses API. The first one-shot workflow run (`31603141860`) proved the instrumentation boundary but did not execute a model because the repository did not expose `OPENAI_API_KEY`.

Before any stochastic P/S/G/R outcome was observed, an available Z.AI Coding endpoint was identified. The instrumentation stack was therefore extended with a second provider adapter rather than changing the causal runner, frozen corpus, question, accepted answer, scoring implementation, or P/S/G/R substrate mechanics.

## Z.AI instrumentation configuration used by the pilot

- Provider: Z.AI
- Requested model: `glm-5.1`
- Protocol: OpenAI-compatible Chat Completions
- Base URL: `https://api.z.ai/api/coding/paas/v4`
- Authentication environment variable: `ZAI_API_KEY`
- Thinking: enabled
- Preserved thinking across tool rounds: enabled with `clear_thinking: false`
- Structured final output: JSON object mode plus explicit client-side schema validation
- Tool interface: unchanged substrate-neutral subject-list and exact-retrieval tools
- Sampling temperature: `1.0`

The adapter preserves returned `reasoning_content` across tool rounds, but reasoning content is not written into the epistemic event log, scoring surface, or experiment artifact.

## Causal invariants preserved

This provider revision did **not** change:

1. producer-once execution per case;
2. canonical event-log hashing;
3. identical event-log replay into P/S/G/R;
4. the validated 138–141 substrate implementations;
5. source assignment or frozen source bytes;
6. source-controlled timestamps;
7. frozen relation ontology;
8. evaluator common tools;
9. five randomized evaluator draws per arm;
10. accepted answers, required evidence-source labels, scoring, or primary endpoint;
11. confirmatory access guards.

## Live instrumentation history

The first credentialed live attempt exposed a JSON-mode/schema issue: a producer returned categorical confidence text instead of a numeric `[0,1]` value. That run failed before event-log creation and before any arm score existed.

The adapter was repaired to embed the expected JSON Schema, validate it client-side, reject invalid confidence types without coercion, and retry schema-invalid output a bounded number of times. Regression tests were green before the next outcome-bearing run.

The complete v2 pilot then succeeded in workflow run `31608304587`. Full results are recorded in `docs/llm-epistemic-substrate-142-145-pilot-results.md`.

## Returned model identity finding

Although the v2 workflow requested `glm-5.1`, every evaluator completion in the successful artifact reported `glm-5.2` as the returned model identity.

This record does not assume or claim that `glm-5.1` is a documented alias for `glm-5.2`. It records an observed requested/returned identity mismatch. Current instrumentation code now persists observed evaluator identities and is being hardened to persist the actual producer response identity as well.

A confirmatory model freeze is therefore impossible until the provider/model contract is explicit and the sealed workflow can reject unexpected returned model identities.

## Coding Plan usage boundary

Current Z.AI documentation and subscription terms restrict the Coding Plan endpoint to supported coding tools/scenarios and caution against using Coding Plan quota as unrestricted general-purpose API access.

Accordingly, no additional custom paid experiment calls should be launched through the Coding Plan endpoint unless the project has an authorized usage basis for this runner. The completed Python/PyPA pilot remains a valid instrumentation/audit record, but scaling should use an authorized provider route such as Z.AI's general API endpoint with appropriate billing/permissions or another provider whose terms permit the experiment.

## Current status

- One complete stochastic instrumentation case exists.
- It is non-inferential and ceiling-saturated on primary accuracy.
- No confirmatory case has been opened or evaluated.
- The provider/model identity must be resolved before confirmatory sealing.
- Further paid Coding Plan calls are paused pending an authorized provider path.
