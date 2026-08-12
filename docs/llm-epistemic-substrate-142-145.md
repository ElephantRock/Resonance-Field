# LLM Epistemic Substrate Replication — Experiments 142–145

## Status

Instrumentation outcome-tuning is closed after Calibration 008. One stochastic pilot and seven numbered calibration cases were attempted; Calibration 007 was stopped by the preregistered pre-replay temporal-conflict gate and produced no treatment outcome. All instrumentation evidence remains non-inferential.

**Protocol Revision 001 increases the planned confirmatory cohort from 96 to 512 independent cases while preserving the 3-pp R−G minimum-effect target.** The 512 confirmatory cases remain uncreated, unobserved, unsealed, and inaccessible.

The current instrumentation record shows repeated retrieval-efficiency advantages for structured G/R substrates over P/S and repeated hard-budget fragility in S. It **does not establish a replicated primary accuracy advantage for R over G**. Calibration 006 produced one frozen case-level R > G split; Calibration 008—the cleanest exact stale/current changed-value test—produced an R/G accuracy tie.

Key pre-confirmatory records:

- `docs/llm-epistemic-substrate-142-145-instrumentation-stop.md`
- `docs/llm-epistemic-substrate-142-145-confirmatory-design-adequacy.md`
- `docs/llm-epistemic-substrate-142-145-protocol-revision-001-sample-size.md`

## Objective

Replicate Experiments 138–141 under stronger external-validity conditions: naturalistic human-authored evidence, stochastic LLM producer agents, and stochastic LLM evaluator agents.

The causal question is unchanged: given the same collective experience, how much persistent capability is attributable to the substrate left behind after producer-local state is destroyed?

## Arms

- **142 / Pile (P):** opaque persistent producer reports.
- **143 / Shared Memory (S):** flat shared retrieval with provenance.
- **144 / Provenance Graph (G):** typed claim/entity/evidence graph with provenance.
- **145 / Resonance Field (R):** G plus frozen activation, decay, independent-confirmation, contradiction, and bridge dynamics.

## Critical causal isolation: producers run once

For each case, producers receive frozen source bundles once and emit one **canonical epistemic event log**. That log is hashed and replayed byte-identically into P/S/G/R.

Producer variation therefore cannot become a hidden treatment. Across arms, deposited evidence is identical; only representation, retrieval, relational structure, and R field dynamics differ.

Producer-local conversational state, scratchpads, tool state, and transient memory are destroyed before substrate evaluation.

## Canonical event contract

Every event contains at least:

- event ID, case ID, producer ID;
- source ID and source SHA-256;
- subject, predicate, object;
- confidence in `[0,1]`;
- timezone-aware evidence timestamp.

Optional fields include source locator, support/contradiction links, uncertainty, and non-treatment metadata.

The event log is substrate-neutral. Producers cannot write arm names, graph centrality, field activation, retrieval scores, or evaluator outcomes. Instrumentation artifacts retain the full canonical event-log payload plus its SHA-256.

## Frozen corpus semantics

Evidence is naturalistic but frozen. No live web is available during evaluation.

Every source is pinned with cryptographic provenance. Each case manifest records source IDs/hashes, acquisition metadata, evidence-state time, producer allocation, held-out question, and scoring contract.

`evidence_observed_at` prospectively separates evidence-state time from byte acquisition time. Historical manifests without it retain their original mapping.

No producer may receive all preregistered required answer evidence.

### Producer-deposit floor

Cases may declare `minimum_events_per_producer`. The canonical log must satisfy that floor before any substrate replay or evaluator execution.

### Exact temporal-conflict floor

Temporal cases may declare `minimum_temporal_conflict_keys`. Before replay, the producer log must contain the required number of cross-producer, cross-time exact `(subject,predicate)` keys with differing objects.

A document-level stale/current conflict that does not survive stochastic producer normalization as the same claim key is therefore not counted as a treatment test.

### Gate-failure audit retention

After Calibration 007, pre-replay deposit/collision failures retain the rejected canonical producer log, hash, producer counts, gate diagnostics, and explicit `replay_attempted: false` / `evaluator_execution_attempted: false` fields while still returning a failing exit code. A failed pre-replay case never becomes a treatment outcome.

## Cohorts

- **Instrumentation ceiling:** 24 cases. Outcome-bearing tuning stopped after Calibration 008.
- **Confirmatory plan:** **512 held-out independent cases** after Protocol Revision 001.

The original 96-case scaffold was revised before any confirmatory content existed because it was not adequately aligned with the 3-pp R−G target when cases are treated as the independent units.

Instrumentation outcomes cannot be pooled into confirmatory inference.

## Provider/model identity

Instrumentation currently requests Z.AI model string `glm-5.1`, while successful artifacts report provider-returned producer/evaluator identity `glm-5.2`. Requested and returned identities are retained separately.

The confirmatory seal must freeze and enforce a returned-model identity policy. A requested alias alone is not sufficient scientific identity control.

Producer agents see only the research brief and assigned frozen sources. They do **not** receive accepted answers, semantic scoring requirements, forbidden terms, or required-source labels.

## Evaluator boundary

Evaluators receive only the held-out question and substrate-backed retrieval tools; they cannot read the raw corpus or producer state.

Common tools:

1. `list_epistemic_subjects` — subject names only; no objects/answers;
2. `retrieve_epistemic_events(subject, predicate)` — arm-specific retrieval under the common policy.

Each case/arm has five independent stochastic evaluator draws.

## Frozen evaluator resource controls

Every arm shares:

- 12 retrieval-operation units per factual call;
- **24 total retrieval-operation units per answer**;
- **8 tool rounds per answer**;
- zero-cost subject discovery;
- mandatory tool-free finalization when a resource boundary is reached.

Mechanical fixes never increased those ceilings.

Z.AI transient business codes 1302/1305 use bounded explicit retry/backoff. Quota, subscription, and policy failures stop immediately; SDK-internal retries are disabled inside the wrapper.

## Primary endpoint and scoring

The single primary endpoint is **post-agent task accuracy** after producer-local state has been destroyed.

Scoring is deterministic and arm-blind.

Historical cases retain their frozen scorer. Calibrations 003 and 005 exposed two known scorer limitations and remain frozen with diagnostic audits rather than retroactive primary rescoring.

Prospective multi-value cases use ordered `required_slots`: answers must contain the exact semicolon-delimited slot count and each slot is checked only against preregistered alternatives. Optional forbidden contradictory terms remain available.

Retrieval efficiency, provenance quality, and other diagnostics remain secondary. They are **not promoted to primary** after observing instrumentation results.

## Planned contrasts and minimum effects

Planned paired contrasts:

1. S − P
2. G − S
3. R − G
4. R − P

Scientific priorities:

- **R − G:** incremental field value beyond a static graph;
- **R − P:** total substrate value.

Minimum-effect targets remain unchanged:

- R − G: **+0.03 absolute**;
- R − P: **+0.08 absolute**.

Protocol Revision 001 preserved these thresholds and increased independent cases instead of weakening the R−G target to fit the original 96-case budget.

## Confirmatory statistical estimator

Cases are the independent experimental units. Evaluator draws are nested repeated measurements and are not treated as independent observations.

Implementation: `src/resonance/experiments/llm_epistemic_confirmatory_analysis.py`.

For each case/arm:

1. reduce the five binary evaluator outcomes to one mean accuracy;
2. compute paired case-level arm differences;
3. bootstrap **cases** for the 95% interval with 10,000 resamples;
4. perform 100,000 paired randomization resamples by within-case arm-label swapping;
5. Holm-adjust the four preregistered contrast p-values at family-wise alpha 0.05.

The implementation explicitly prevents evaluator-draw pseudoreplication.

The minimum-effect criterion is reported separately from the zero-effect randomization test; the pre-confirmatory protocol must freeze the final success/interpretation rule before sealing.

## Sample-size revision and adequacy

The original 96-case scaffold had approximate 80%-power resolution of about 6.1 pp for R−G under the instrumentation planning SD (`≈0.1789`) and a conservative first Holm threshold.

Approximate independent cases required for a 3-pp R−G effect were:

| Planning paired SD | Approx. cases |
| ---: | ---: |
| 0.150 | 279 |
| 0.175 | 380 |
| 0.1789 | 397 |
| 0.200 | 496 |
| 0.225 | 628 |

Protocol Revision 001 selects **512 cases**, providing first-order planning margin through paired SD around 0.20 while preserving the 3-pp target.

This revision uses instrumentation only for variance/precision planning, not for the target mean effect. No confirmatory content existed at revision time.

A final deterministic power/simulation check tied to the frozen estimator and evaluable-case rule is still required before case construction.

## Hard confirmatory gates

A confirmatory result is admissible only if the sealed protocol requires and verifies at least:

- identical canonical event-log hash across all arms for each evaluated case;
- full canonical event log retained;
- identical evaluator model/prompt/context/resource policy across arms;
- provider-returned model identity satisfies the sealed policy;
- producer-local state is unavailable to evaluators;
- no live web during evaluation;
- no mutable cross-arm state reuse;
- event provenance completeness at least 0.99;
- unsupported-synthesis rate at most 0.05;
- confirmatory source/case manifest hashes match the seal;
- no treatment, metric, scoring, sample-size, or analysis changes after unsealing.

The protocol still needs a frozen rule for arm-independent pre-replay gate failures after sealing, including the minimum evaluable-case count and prohibition on outcome-driven replacement.

## Instrumentation chronology

### Pilot 001 — Python packaging
Run `31608304587`: P/S/G/R all 5/5. End-to-end pipeline validated; primary ceiling-saturated.

### Calibration 002 — Python annotations
Run `31617588775`: P 4/5, S/G/R 5/5. Mean retrieval units P 23.4, S 24.0, G 15.8, R 11.8. R−G = 0.

### Calibration 003 — Rust 2024
Run `31620858330`. Frozen whole-string scorer: P 5/5, S 3/5, G 2/5, R 4/5. Diagnostic semantic completeness: P 5/5, S 3/5, G 5/5, R 5/5. Historical score retained.

### Calibration 004 — Go toolchain
Run `31624101126`: all arms 5/5. Mean retrieval units P 20.4, S 18.6, G 7.8, R 7.0. Intended distractor producer deposited zero events, motivating the producer floor.

### Calibration 005 — Kubernetes PSP → PSA
Run `31631639325`. Frozen unordered semantic score P 1/5, S 0/5, G 2/5, R 2/5; ordered-slot diagnostic P 5/5, S 1/5, G 5/5, R 5/5. S exhausted all 24 units in every draw. The intended temporal contradiction did not survive as an exact opposing claim key, motivating ordered slots and the exact collision floor.

### Calibration 006 — PostgreSQL `password_encryption`
Run `31634337448`: exact `password_encryption / default_is: md5 → scram-sha-256` collision present. P 4/5, S 4/5, G 3/5, R 5/5; mean retrieval P 17.4, S 23.6, G 5.4, R 5.8. First prospectively frozen case-level R > G split, but audit traced G failures to semantic-status precision rather than stale-default selection.

### Calibration 007 — OpenJDK gate abort
Run `31636162375`: producer deposit passed, then pre-replay collision floor failed with `minimum=1; observed=0`. No substrate replay or evaluator draw occurred. No treatment outcome exists.

### Calibration 008 — PostgreSQL `wal_level`
Run `31638592754`, artifact `9158146739`. The 124-event log contained nine exact cross-time differing-object keys, including `wal_level / default_is: minimal (2016) → replica (2026)`.

| Arm | Correct | Mean retrieval units |
| --- | ---: | ---: |
| P | 5/5 | 23.4 |
| S | 3/5 | 24.0 |
| G | 5/5 | 8.6 |
| R | 5/5 | 7.6 |

R−G = 0.00 and R−P = 0.00. S exhausted the 24-unit budget in every draw. P/G/R cited current required evidence with perfect provenance precision/recall/F1. This is the cleanest fulfilled exact temporal-conflict design and **does not replicate** Calibration 006's R > G primary split.

Detailed result records are stored under `docs/llm-epistemic-substrate-142-145-*-results.md`.

## Instrumentation anti-tuning boundary

After Calibration 008:

- no additional outcome-bearing case may tune P/S/G/R definitions;
- resource ceilings are frozen against outcome-driven changes;
- scorer semantics cannot be changed to rescue an observed arm;
- retrieval efficiency remains secondary;
- minimum effects cannot be moved toward observed instrumentation effects;
- completed cases cannot be rerun solely to seek favorable stochastic draws;
- failed pre-replay cases cannot be admitted by weakening gates.

Mechanical, provider-compatibility, fixed-scope variance, or dry-run work may continue only if declared prospectively and cannot be used to chase R > G accuracy.

## Remaining pre-confirmatory freeze work

Before any of the 512 cases are created, freeze:

1. returned-model identity policy;
2. exact provider, prompt, generation, structured-output, retry, and state-retention policy;
3. domain and case-type strata plus source eligibility/allocation rules;
4. final scoring conventions and empty/resource-boundary handling;
5. deterministic 512-case power simulation and minimum evaluable-case rule;
6. final success/interpretation rule for statistical significance plus minimum effects;
7. immutable confirmatory manifest/seal procedure.

Current boundary:

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- planned confirmatory cases: `512`
- confirmatory cases created: false
- confirmatory cases sealed: false

No confirmatory case may be opened until these choices are frozen.
