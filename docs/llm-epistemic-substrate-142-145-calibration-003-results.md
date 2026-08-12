# Experiments 142–145 — Rust Calibration 003 Results

Date: 2026-08-12
Status: instrumentation-only; non-inferential; primary exact-string score format-confounded
Case: `instr-rust-edition-003`
Provider endpoint: Z.AI Coding endpoint (`https://api.z.ai/api/coding/paas/v4`)

## Frozen design

Calibration 003 moved the same resource-constrained design into the Rust ecosystem. Before any Rust outcome existed, the project froze:

- four commit-pinned Rust Edition Guide sources at commit `f9e4d77fa7a0c7cb289e1da53a11160394bb31af`;
- one source per producer;
- three required facts distributed across three producers;
- a Rust 2021 reserved-syntax document as an older-edition distractor;
- five evaluator draws per P/S/G/R arm;
- 12 retrieval-operation units per call; and
- 24 total retrieval-operation units per evaluator answer.

The held-out task asks for the Rust edition migration command, the new 2024 reserved keyword, and both newly unsafe `std::env` functions.

Frozen plan SHA-256:

`339a94b5dbd2742b25bd00cad24caff4b53dfc42b7be3a720a2571f5cb027acb`

Frozen manifest SHA-256:

`e82be067a5fa97fb4435f863132546aef8b0b7b7ae9106e84c40b6a9176a6a19`

## Execution chronology

### v1 — transient provider failure, no accepted result

Workflow run `31619528557` passed implementation, seal, source-freeze, and credential checks. During the live evaluator phase Z.AI returned HTTP 429, business code `1302`, `Rate limit reached for requests`. The workflow produced no result artifact and therefore no accepted arm score.

Z.AI documents code 1302 as request-rate limiting, distinct from quota-exhaustion and subscription-limit 429 codes. The transport was repaired to retry only transient codes 1302 and 1305 with bounded exponential backoff (2, 4, 8, 16, 32 seconds; at most five retries). Quota, subscription, and policy-limit 429 codes are not retried. The OpenAI SDK's internal retry count is set to zero inside this wrapper so the retry envelope is explicit.

The retry repair changed no scientific input. Ordinary CI and the dedicated instrumentation suite passed before v2 was triggered.

### v2 — SUCCESS

Workflow run: `31620858330`
Head SHA: `d9430503b5a89fe1539ad9297c1f3a52c8c89d57`
Artifact ID: `9151555431`
Artifact digest: `sha256:d8dcd78f0b4f1584df4575ad9145fb0e79dc628b0a7aee330b79d557deb90c80`
Event count: `50`
Event-log SHA-256: `d7ce43ebf8fd7adfae37c9347bbf249ed7e86967fc3b90352a4541ea849a9ae0`
Requested model: `glm-5.1`
Observed producer model: `glm-5.2`
Observed evaluator model: `glm-5.2`

The artifact contains the complete canonical event log. Recomputing SHA-256 over canonical JSON reproduces the stored event-log digest exactly.

## Raw preregistered exact-string score

| Arm | Correct draws | Mean accuracy | Mean retrieval units | Draws at 24-unit ceiling | Unsupported synthesis |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pile (P) | 5 / 5 | 1.000 | 16.8 | 0 / 5 | 0.000 |
| Shared Memory (S) | 3 / 5 | 0.600 | 23.0 | 3 / 5 | 0.000 |
| Provenance Graph (G) | 2 / 5 | 0.400 | 5.8 | 0 / 5 | 0.000 |
| Resonance Field (R) | 4 / 5 | 0.800 | 6.6 | 0 / 5 | 0.000 |

These raw numbers must **not** be interpreted as evidence that P > G. Calibration 003 exposed a deterministic scoring-format defect.

## Exact-string scoring confound

The frozen accepted-answer list allowed the two unsafe functions to be joined with a comma or the word `and`. Several evaluators instead returned the same correct values with a semicolon between the two function names:

`cargo fix --edition; gen; std::env::set_var; std::env::remove_var`

The existing scorer performs normalized whole-string membership and therefore marked this semantically correct output wrong.

Affected draws:

- G draws 1, 3, and 5;
- R draw 2.

Every one of those answers contains all four requested values and no contradictory answer value. Their failures are formatting failures, not evidence-retrieval failures.

A deterministic post-hoc semantic-completeness audit that asks only whether all four frozen target terms are present gives:

| Arm | Semantically complete draws | Genuine incomplete draws |
| --- | ---: | ---: |
| P | 5 / 5 | 0 / 5 |
| S | 3 / 5 | 2 / 5 |
| G | 5 / 5 | 0 / 5 |
| R | 5 / 5 | 0 / 5 |

This audit is diagnostic only; it does not replace or rewrite the frozen raw primary score.

## Genuine S failures

S draws 2 and 4 returned an empty answer at confidence `0.1` after reaching the full 24-unit retrieval ceiling. These are genuine incompleteness events under the frozen evaluator contract rather than punctuation mismatches.

## Secondary diagnostics

| Arm | Evidence-path F1 | Provenance precision | Provenance recall | Raw-score Brier | Mean input tokens | Mean output tokens | Mean latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P | 0.840 | 1.000 | 0.733 | 0.0005 | 10122.6 | 1013.0 | 25375.8 |
| S | 0.640 | 0.800 | 0.533 | 0.0125 | 6982.0 | 916.0 | 22363.6 |
| G | 0.880 | 1.000 | 0.800 | 0.5610 | 9126.0 | 878.4 | 25708.2 |
| R | 0.960 | 1.000 | 0.933 | 0.2010 | 14548.8 | 1318.6 | 35528.0 |

The Brier values for G/R are also contaminated by the same exact-string scoring defect and should not be interpreted as calibration quality for the semantically correct punctuation-variant draws.

## Scientific consequence

Calibration 003 is primarily an **instrumentation finding**, not an accuracy treatment estimate.

It supports three conclusions for the next tranche:

1. the 24-unit resource ceiling can produce genuine incompleteness in S across a second software ecosystem;
2. G/R retrieve the needed Rust evidence with substantially fewer operation units than S, while P happened to solve this particular case efficiently enough; and
3. whole-string accepted-answer enumeration is inadequate for multi-part naturalistic tasks and must be replaced prospectively with a deterministic semantic requirement contract before new calibration cases are scored.

Calibration 003 itself will remain frozen with its original raw score plus this audit. It will not be retroactively modified or pooled as if its original exact-string primary metric were valid.

## Seal status

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- 96 confirmatory cases remain uncreated/unobserved.
