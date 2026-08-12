# Experiments 142–145 — Kubernetes Temporal Calibration 005 Results

Date: 2026-08-12
Status: instrumentation-only; non-inferential; prospectively semantic-scored
Case: `instr-kubernetes-psp-005`
Provider endpoint: Z.AI Coding endpoint (`https://api.z.ai/api/coding/paas/v4`)

## Purpose

Calibration 005 moved the harder replication into a fourth software ecosystem and deliberately introduced stale/current evidence. Three current Kubernetes sources describe PodSecurityPolicy removal and Pod Security Admission behavior. A fourth official Kubernetes article from 2019 describes PodSecurityPolicy as a recommended built-in admission controller.

This was also the first case to use both:

- a distinct frozen `evidence_observed_at` timestamp, separate from source acquisition time; and
- `minimum_events_per_producer: 1`, which aborts before substrate replay/evaluation if any assigned producer contributes no events.

Historical source manifests without either optional field retain their previous canonical representation.

## Frozen design

All four files were acquired from `kubernetes/website` at commit:

`22cc5093581b4dc74394bdce60753d5caf13ddf0`

All files were acquired on 2026-08-12. The three current documentation sources have evidence time `2026-08-12T19:00:00Z`; the historical article has evidence time `2019-03-21T00:00:00Z`.

The held-out question requested four values in order:

1. the Kubernetes release that removed PodSecurityPolicy;
2. the built-in replacement admission controller;
3. whether that replacement mutates Pods before validation; and
4. the namespace label key that enforces a selected Pod Security level.

The prospectively frozen semantic targets were:

- `v1.25` / `1.25`;
- Pod Security Admission variants;
- lexical non-mutation variants such as `non-mutating`, `does not mutate`, etc.; and
- `pod-security.kubernetes.io/enforce`.

`PodSecurityPolicy` / `Pod Security Policy` was preregistered as a forbidden contradictory answer term.

Common evaluator controls remained unchanged:

- five draws per arm;
- 12 retrieval-operation units per factual call;
- 24 total retrieval-operation units per answer;
- 8 tool rounds per answer;
- forced tool-free finalization at either boundary.

Frozen plan SHA-256:

`f6d5f8c5296d5a2659bded2408ee3e2659fe281ebe7df65c8285cbb149ba5346`

Frozen manifest SHA-256:

`6da46f034e301559e744397890f2b5f082cae501cc52728d85d2fb3a45d0b9d8`

## Execution — SUCCESS

Workflow run: `31631639325`
Head SHA: `4dc2f252275ca1bc3c1647f344d796297a2c1a46`
Artifact ID: `9155621236`
Artifact digest: `sha256:657d4618c8ed5e13e6d8862ae824266651a9a9178841cc3911a71e373cfc30d8`
Event count: `126`
Event-log SHA-256: `2fec12a1e8180b14c80585b9d2e3f2afb3bac7972652d70912152823a19498cb`
Requested model: `glm-5.1`
Observed producer model: `glm-5.2`
Observed evaluator model: `glm-5.2`

The complete canonical event log is present in the artifact. Recomputing SHA-256 over canonical compact JSON reproduces the stored event-log digest exactly.

## Producer-deposit guard — PASS

All four producers deposited nonzero evidence before replay:

| Producer | Role | Events |
| --- | --- | ---: |
| `producer-k8s-removal` | current PSP removal page | 14 |
| `producer-k8s-admission` | current PSA concept | 31 |
| `producer-k8s-migration` | current migration guide | 47 |
| `producer-k8s-stale` | 2019 PSP-era article | 34 |

The guard therefore fixed the Calibration 004 failure mode in which an intended distractor producer emitted zero events.

## Frozen primary score

The prospectively frozen bag-of-terms semantic scorer produced:

| Arm | Raw correct draws | Raw accuracy | Mean retrieval units | Draws at 24-unit ceiling | Unsupported synthesis |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pile (P) | 1 / 5 | 0.200 | 21.0 | 1 / 5 | 0.000 |
| Shared Memory (S) | 0 / 5 | 0.000 | 24.0 | 5 / 5 | 0.000 |
| Provenance Graph (G) | 2 / 5 | 0.400 | 10.4 | 0 / 5 | 0.000 |
| Resonance Field (R) | 2 / 5 | 0.400 | 8.6 | 0 / 5 | 0.000 |

These raw primary values are retained unchanged as the original frozen score.

## Scoring-contract miss: contextual boolean answers

The raw P/G/R failures are mostly not substantive answer failures. The question explicitly asks **whether** Pod Security Admission mutates Pods before validation. Most evaluators answered the third slot as `No`, which is semantically correct in that question context. The preregistered third required group, however, contained lexical forms such as `non-mutating`, `does not mutate`, and `won't modify pods`, but did not include the contextual value `No`.

Examples that were scored incorrect despite containing the correct four requested values include:

`Kubernetes v1.25; PodSecurity admission controller; No; pod-security.kubernetes.io/enforce`

The one P draw and the two G/R draws scored correct by the frozen scorer happened to expand the boolean slot with text such as `non-mutating`.

This exposes a limitation of unordered bag-of-terms semantic requirements for position-dependent answers. Calibration 005 is **not retroactively rescored**. A prospective slot-aware deterministic scorer should be added before future multi-slot cases that contain contextual booleans or similarly position-dependent values.

## Diagnostic slot-aware semantic completeness

For diagnosis only, the answer strings were split into the four requested semicolon-delimited slots. Slot 3 was treated as correct when it began with `No` or contained one of the preregistered non-mutation lexical forms. All other preregistered requirements and forbidden terms were preserved.

| Arm | Diagnostic correct draws | Diagnostic completeness |
| --- | ---: | ---: |
| P | 5 / 5 | 1.000 |
| S | 1 / 5 | 0.200 |
| G | 5 / 5 | 1.000 |
| R | 5 / 5 | 1.000 |

The four S diagnostic failures are genuine empty answers after consuming the full 24-unit retrieval budget. The remaining non-empty S draw contains the correct four values but is misclassified by the frozen boolean lexical contract in the same way as the P/G/R `No` answers.

This diagnostic must not be substituted for the frozen primary score in inference.

## Retrieval-efficiency diagnostic

Per-draw retrieval-operation units were:

| Draw | P | S | G | R |
| --- | ---: | ---: | ---: | ---: |
| 1 | 21 | 24 | 15 | 12 |
| 2 | 18 | 24 | 8 | 12 |
| 3 | 21 | 24 | 6 | 5 |
| 4 | 21 | 24 | 13 | 8 |
| 5 | 24 | 24 | 10 | 6 |

Mean units:

- P: `21.0`
- S: `24.0`
- G: `10.4`
- R: `8.6`

R used 59.0% fewer mean retrieval units than P, 64.2% fewer than S, and 17.3% fewer than G. G used 50.5% fewer than P and 56.7% fewer than S.

The G–R difference remains a secondary, single-case instrumentation observation and is not inferential.

## Provenance diagnostics

Mean evidence-path / provenance metrics from the frozen artifact:

| Arm | Evidence-path F1 | Provenance precision | Provenance recall |
| --- | ---: | ---: | ---: |
| P | 0.960 | 1.000 | 0.933 |
| S | 0.160 | 0.200 | 0.133 |
| G | 0.880 | 1.000 | 0.800 |
| R | 0.920 | 1.000 | 0.867 |

S's low values are driven by four empty, uncited answers. Unsupported synthesis remains zero in all arms.

## Temporal-conflict audit

The stale source was genuinely deposited with 34 events at `2019-03-21T00:00:00Z`, while the three current sources produced 92 events at `2026-08-12T19:00:00Z`.

However, the canonical ontology projection did **not** create a strong exact-key contradiction:

- only one `(subject, predicate)` key overlapped between the stale producer and any current producer: `("PodSecurityPolicy", "is_a")`;
- that key was not a clean opposing-value conflict—the stale event called PSP an `admission controller`, and a current migration event also describes PSP as an `admission controller` in historical/migration context;
- no final cited evidence path in any arm cited an event from `producer-k8s-stale`.

Therefore Calibration 005 establishes **active stale deposition**, but it does not establish that evaluators had to resolve a treatment-relevant exact stale/current contradiction. The intended R-specific temporal mechanism remains under-tested.

A stronger future temporal case should preregister sources likely to emit the **same subject and predicate with opposing old/current objects**, for example a changed default value or superseded configuration whose ontology projection naturally maps both eras to `default_is` or another shared relation.

## Scientific consequence

Calibration 005 supports several instrumentation conclusions but no R > G primary claim:

1. the producer-deposit guard works—every intended producer contributed evidence before replay;
2. separate evidence timestamps can be frozen without overloading acquisition time;
3. S again shows severe failure under the common 24-unit resource ceiling on this larger evidence log;
4. P/G/R all contain the correct substantive answer in every draw under a slot-aware diagnostic;
5. R remains directionally more retrieval-efficient than G (`8.6` vs `10.4`) with no substantive accuracy difference;
6. the semantic scorer needs a prospective slot-aware contract for contextual values; and
7. source-level temporal conflict is insufficient if producer ontology projection does not yield treatment-relevant overlapping claim keys.

No Calibration 005 observation is confirmatory evidence and it will not be pooled into confirmatory inference.

## Seal status

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- 96 confirmatory cases remain uncreated/unobserved.
