# Experiments 142–145 — Harder Calibration 002 Results

Date: 2026-08-12
Status: instrumentation-only; non-inferential
Case: `instr-python-annotations-002`
Provider endpoint: Z.AI Coding endpoint (`https://api.z.ai/api/coding/paas/v4`)

## Frozen design

This case was created after the first stochastic pilot saturated at 100% accuracy in all arms. Before any Calibration 002 outcome existed, the experiment froze:

- four commit-pinned naturalistic Python sources;
- one source per producer;
- three required evidence sources distributed across three separate producers;
- PEP 563 as a superseded but plausible distractor regime;
- five evaluator draws per P/S/G/R arm;
- 12 retrieval-operation units per retrieval call; and
- **24 total retrieval-operation units per evaluator answer**.

The held-out question asks for three linked current-semantics facts: PEP 649 as the deferred-evaluation model, `annotationlib` as the implementation/introspection module, and `Format.STRING` as the current string-format enum member.

Frozen plan SHA-256:

`6165bbc6e0082a8a897ed1a9a304b6b339013501e50277c2f08a4a24af12f81d`

Frozen manifest SHA-256:

`4cd08d5a4c4c872a9105816af9fda079fcc17fe0a126bf0d6dd8599d6a0b35b7`

## Execution chronology

### v1 — mechanical failure, no accepted score

Workflow run `31616444390` completed all preflight, seal, source-freeze, and credential checks, then failed in the evaluator because a model continued requesting retrieval tools after the new 24-unit total budget was exhausted. The legacy eight-tool-round guard eventually raised `evaluator exceeded maximum retrieval rounds`.

No calibration artifact or accepted arm score was produced by v1.

The repair did **not** change the corpus, question, accepted answers, P/S/G/R substrates, per-call budget, total budget, or evaluator draw count. It only forces tool-free final-answer generation after the frozen retrieval budget reaches zero. The repair passed ordinary CI on Python 3.12/3.13 and the dedicated instrumentation suite before v2 was triggered.

### v2 — SUCCESS

Workflow run: `31617588775`
Head SHA: `8ebbde025c6962bf4f8594844e23873979eaa0ae`
Artifact ID: `9150351574`
Artifact digest: `sha256:f135c9937b7c4b5d7f769401bb9556dce358cea45ecd0de8d0cb9c3567669adc`
Event count: `156`
Event-log SHA-256: `8e7fc71f89fd980cee4127dc383381ee52cbad23857e0073181fd0827b55da8a`
Observed producer model: `glm-5.2`
Observed evaluator model: `glm-5.2`
Requested model: `glm-5.1`

The artifact contains the complete canonical event log; recomputing SHA-256 over its canonical JSON reproduces the stored event-log digest exactly.

## Primary calibration result

| Arm | Correct draws | Mean accuracy | Mean retrieval units | Draws at 24-unit ceiling | Unsupported synthesis |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pile (P) | 4 / 5 | 0.800 | 23.4 | 4 / 5 | 0.000 |
| Shared Memory (S) | 5 / 5 | 1.000 | 24.0 | 5 / 5 | 0.000 |
| Provenance Graph (G) | 5 / 5 | 1.000 | 15.8 | 0 / 5 | 0.000 |
| Resonance Field (R) | 5 / 5 | 1.000 | 11.8 | 0 / 5 | 0.000 |

Raw one-case accuracy contrasts are therefore:

- R − P: +0.20
- G − P: +0.20
- S − P: +0.20
- R − G: 0.00

These are **instrumentation observations, not treatment-effect estimates**. Five stochastic draws from one case are not an independent case sample and must not be used as confirmatory inference.

## Failure mode in P

Pile failed draw 4 with high confidence (`0.98`), answering:

`PEP 749; annotationlib; Format.STRING`

instead of the frozen accepted answer beginning with PEP 649. Its cited evidence covered PEP 749, `annotationlib`, and `Format.STRING`, but omitted direct PEP 649 evidence. The draw consumed the full 24-unit retrieval budget. This is consistent with a search/resource failure under the pile representation, though one draw cannot establish the mechanism causally.

## Secondary diagnostics

| Arm | Evidence-path F1 | Provenance precision | Provenance recall | Calibration Brier | Mean input tokens | Mean output tokens | Mean latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P | 0.813 | 0.933 | 0.733 | 0.1941 | 7244.8 | 822.8 | 22024.2 |
| S | 0.600 | 1.000 | 0.467 | 0.1065 | 3254.4 | 1168.2 | 22720.0 |
| G | 0.758 | 0.817 | 0.733 | 0.0021 | 13094.6 | 1211.2 | 31068.0 |
| R | 0.880 | 1.000 | 0.800 | 0.0020 | 9087.2 | 825.8 | 23629.6 |

The clearest resource diagnostic is that S exhausted the common retrieval budget in every draw and P in four of five, whereas neither graph arm exhausted it. R used four fewer retrieval units than G on average (11.8 vs 15.8) while both remained 5/5 accurate.

This is the first stochastic naturalistic case in the campaign where the common resource ceiling creates an observed primary accuracy difference between an unstructured arm and structured arms. It still does **not** establish an incremental R > G accuracy effect.

## Scientific consequence

Calibration 002 is substantially more discriminating than the original packaging pilot and supports retaining three design elements for the next instrumentation tranche:

1. multi-part questions requiring evidence distributed across at least three producers;
2. plausible superseded/proposed/current-regime distractors; and
3. the common 24-unit total retrieval-operation ceiling.

The next calibration cases should vary the underlying software domain and conflict structure rather than replicate this exact Python-annotation question. A small multi-case calibration tranche is needed before deciding that difficulty is appropriately centered for the 24-case instrumentation cohort.

## Seal status

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- 96 confirmatory cases remain uncreated/unobserved.
