# Experiments 142–145 — Provider Revision: Z.AI GLM-5.1

Date: 2026-08-12
Status: instrumentation-only, pre-outcome protocol revision

## Reason for revision

The original stochastic instrumentation candidate was `gpt-5.6-terra` through the OpenAI Responses API. The first one-shot workflow run (`31603141860`) proved the instrumentation boundary but did not execute a model because the repository did not expose `OPENAI_API_KEY`.

Before any stochastic P/S/G/R outcome was observed, an available Z.AI Coding endpoint was identified. The instrumentation stack was therefore extended with a second provider adapter rather than changing the causal runner, frozen corpus, question, accepted answer, scoring implementation, or P/S/G/R substrate mechanics.

## Z.AI instrumentation candidate

- Provider: Z.AI
- Model: `glm-5.1`
- Protocol: OpenAI-compatible Chat Completions
- Base URL: `https://api.z.ai/api/coding/paas/v4`
- Authentication environment variable: `ZAI_API_KEY`
- Thinking: enabled
- Preserved thinking across tool rounds: enabled with `clear_thinking: false`
- Structured final output: JSON object mode
- Tool interface: unchanged substrate-neutral subject-list and exact-retrieval tools
- Sampling temperature: `1.0`

The adapter preserves returned `reasoning_content` across tool rounds as required by Z.AI's preserved/interleaved-thinking contract, but reasoning content is not written into the epistemic event log, scoring surface, or experiment artifact.

## Scope restriction

Z.AI documents the Coding endpoint as intended for coding scenarios. Therefore this endpoint is approved only for the current Python/PyPA instrumentation pilot and other clearly coding-domain instrumentation unless the project later obtains or explicitly selects Z.AI's general API endpoint.

This revision does not authorize use of the Coding endpoint for non-coding confirmatory cases.

## Causal invariants preserved

This provider revision does **not** change:

1. producer-once execution per case;
2. canonical event-log hashing;
3. identical event-log replay into P/S/G/R;
4. the validated 138–141 substrate implementations;
5. source assignment or frozen source bytes;
6. source-controlled timestamps;
7. frozen relation ontology;
8. evaluator retrieval budget or common tools;
9. five randomized evaluator draws per arm;
10. accepted answers, required evidence-source labels, scoring, or primary endpoint;
11. confirmatory access guards.

## Validation

The Z.AI adapter and provider-selectable CLI passed repository CI on Python 3.12 and 3.13 and passed the dedicated LLM Epistemic Substrate instrumentation test suite before the Z.AI outcome-bearing trigger was created.

One-shot Z.AI workflow run `31604692689` then completed all preflight, corpus-freeze, and confirmatory-seal checks. The model step was skipped because `ZAI_API_KEY` was not present in repository Actions secrets.

Therefore, as of this revision:

- no Z.AI model execution has occurred;
- no stochastic P/S/G/R outcome has been observed;
- no confirmatory case has been opened or evaluated;
- this revision remains pre-outcome and non-inferential.

## Next admissible action

Configure the repository Actions secret `ZAI_API_KEY`, then rerun the already-defined Z.AI stochastic pilot workflow without changing the corpus, task, accepted answer, provider adapter, model candidate, or treatment/scoring mechanics.

A successful instrumentation pilot may motivate further instrumentation changes, but any such change must remain confined to the instrumentation cohort and be documented before confirmatory sealing.
