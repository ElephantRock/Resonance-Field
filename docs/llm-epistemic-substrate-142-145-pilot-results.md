# Experiments 142–145 — Stochastic Pilot Results

Date: 2026-08-12
Status: instrumentation-only; non-inferential
Case: `instr-python-packaging-001`
Provider endpoint: Z.AI Coding Plan (`https://api.z.ai/api/coding/paas/v4`)

## Scientific status

This document records the first complete stochastic producer/evaluator execution of the Epistemic Substrate 142–145 replication. It is **not** a confirmatory result and must not be pooled into future confirmatory inference.

The 96-case confirmatory cohort remained inaccessible throughout all attempts. No confirmatory source, case, score, or outcome was created or evaluated.

## Frozen pilot inputs

The pilot used four immutable, commit-pinned Python/PyPA sources assigned one per producer. The held-out answer required evidence distributed across at least two producer assignments.

Canonical frozen corpus manifest SHA-256:

`961cc1540d00e799c3e1cf3c68b888a9becfa9464d68ab6b862771b1ce1815c8`

Expected answer:

`venv; --break-system-packages`

The corpus, question, accepted answer, source allocation, P/S/G/R implementations, scoring code, and confirmatory guards were not changed in response to arm outcomes.

## Execution chronology

### Preflight without credential

Run `31604692689`, initial attempt, completed all non-model preflight steps but skipped the model step because `ZAI_API_KEY` was not yet available. This produced no stochastic outcome.

### First live attempt — schema failure

After the repository secret was configured, run `31604692689` was rerun. The Z.AI endpoint was invoked successfully, but a producer returned syntactically valid JSON with a categorical confidence value (`"high"`) where the experiment requires a numeric value in `[0,1]`.

The run failed before canonical event-log creation and before any P/S/G/R evaluator outcome existed. No scientific score was accepted from this attempt.

The instrumentation adapter was then repaired to:

- embed the exact expected JSON Schema in the prompt;
- validate types client-side;
- reject categorical or out-of-range confidence values;
- never coerce text confidence into a fabricated numeric value; and
- permit at most two schema-repair retries.

Regression tests for this exact failure mode passed before the next outcome-bearing attempt.

### Complete v2 attempt — SUCCESS

Run: `31608304587`
Head SHA: `6085c66cf75476d0ee06da374d9c6205289c2066`
Artifact ID: `9146430746`
Artifact digest: `sha256:2078dcb67094046c4111599240f16f01b0e0141d41dd68491c6e1ef1a086ccb6`
Event count: `119`
Event-log SHA-256: `0291f3abc9751e678bb64726db54c03643870ae0db952ee071e37d529cc7d1a9`

All four producers completed and all 20 evaluator executions completed: five draws for each of P, S, G, and R.

## Primary result: ceiling saturation

Every evaluator execution returned the accepted answer.

| Arm | Correct draws | Mean accuracy | Unsupported synthesis |
| --- | ---: | ---: | ---: |
| Pile (P) | 5 / 5 | 1.000 | 0.000 |
| Shared Memory (S) | 5 / 5 | 1.000 | 0.000 |
| Provenance Graph (G) | 5 / 5 | 1.000 | 0.000 |
| Resonance Field (R) | 5 / 5 | 1.000 | 0.000 |

Therefore this case **cannot estimate P/S/G/R accuracy differences**. It validates the stochastic end-to-end machinery and post-agent transfer path, but it provides no evidence that R outperforms G, S, or P on the primary endpoint.

## Secondary diagnostics

Means across the five evaluator draws per arm:

| Arm | Evidence-path F1 | Provenance precision | Provenance recall | Retrieval units | Input tokens | Output tokens | Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P | 0.867 | 1.000 | 0.800 | 18.6 | 5928.8 | 578.6 | 19010.6 |
| S | 0.853 | 0.867 | 0.900 | 35.6 | 4811.4 | 524.4 | 16741.6 |
| G | 0.827 | 0.933 | 0.800 | 5.4 | 4409.2 | 520.0 | 22645.2 |
| R | 0.853 | 0.867 | 0.900 | 6.0 | 5023.4 | 587.8 | 21570.8 |

Graph and Resonance required substantially fewer retrieval operation units on this case than Pile and Shared Memory. This is a secondary, one-case instrumentation observation only. It must not be interpreted as a treatment-effect estimate.

Evidence-path and provenance metrics are not monotone across arms in this single case and should not be overinterpreted.

## Provider model identity finding

The workflow requested model identifier `glm-5.1`. Every evaluator completion in the successful artifact reported its returned model identity as `glm-5.2`.

The experiment does **not** infer that `glm-5.1` is formally documented as an alias for `glm-5.2`; no such alias assumption is part of the protocol. The observation is simply that the provider-returned identity differed from the requested identity in this run.

This prevents a confirmatory model freeze on the current configuration. Before confirmatory execution, the instrumentation stack must hard-record both requested and returned producer/evaluator identities and reject an unexpected identity under the final sealed model policy.

Post-pilot engineering now persists the complete canonical event log in instrumentation output and records observed model identities. These changes improve auditability; they do not alter the successful v2 result retroactively.

## Z.AI execution status and provider-use note

The Z.AI stochastic pilot workflow remains **active** for instrumentation at `https://api.z.ai/api/coding/paas/v4` using the repository secret `ZAI_API_KEY`. On 2026-08-12 the workflow was briefly archived after a provider-scope review; that archive was reversed at the project owner's direction before any additional experiment execution. The archive/re-enable sequence is retained in Git history for auditability.

Provider documentation/terms regarding the Coding Plan endpoint remain a recorded operational consideration. They are not encoded as an automatic experiment shutdown policy. Any future decision to disable, archive, replace, or materially restrict the configured provider path should be treated as a project-level operational decision and consulted with the project owner unless an immediate security incident requires containment.

## Instrumentation decision

The correct next scientific step is **not** to scale 23 more cases of the same difficulty. This pilot saturated the primary endpoint.

Before expanding the instrumentation cohort:

1. continue recording requested and returned Z.AI model identities and freeze the final identity policy before confirmatory sealing;
2. preserve full canonical producer event logs in outcome artifacts;
3. curate a harder difficulty-calibration tranche with contradictions, stale/current evidence, multi-hop composition, plausible distractors, and at least three distributed required facts; and
4. freeze a total per-answer retrieval-operation ceiling rather than relying only on a per-call ceiling, so substrate search efficiency is tested under a common resource constraint.

These are instrumentation-stage design controls. They must be finalized before the confirmatory corpus is sealed and must not be tuned against any confirmatory outcome.
