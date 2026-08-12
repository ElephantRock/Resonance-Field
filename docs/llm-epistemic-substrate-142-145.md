# LLM Epistemic Substrate Replication — Experiments 142–145

## Status

Instrumentation only. One stochastic pilot and seven numbered calibration cases have been attempted through Calibration 008. Calibration 007 was deliberately aborted by the pre-replay temporal-conflict gate and produced no treatment outcome; the other completed cases remain non-inferential instrumentation evidence. The 96 confirmatory cases remain uncreated, unobserved, and inaccessible.

The current instrumentation record shows a repeated retrieval-efficiency advantage for structured G/R substrates over P/S and repeated hard-budget fragility in S. It **does not establish a replicated primary accuracy advantage for R over G**. Calibration 006 produced a frozen case-level R > G split, but Calibration 008—the cleanest exact stale/current changed-value test—produced an R/G accuracy tie.

## Objective

Replicate Experiments 138–141 under stronger external-validity conditions: naturalistic human-authored evidence, stochastic LLM producer agents, and stochastic LLM evaluator agents.

The causal question remains unchanged: given the same collective experience, how much persistent capability is attributable to the substrate left behind after the producer agents are gone?

## Arms

- **142 / Pile (P):** opaque persistent producer reports.
- **143 / Shared Memory (S):** flat shared retrieval with provenance.
- **144 / Provenance Graph (G):** typed claim/entity/evidence graph with provenance.
- **145 / Resonance Field (R):** G plus frozen activation, decay, independent-confirmation, contradiction, and bridge dynamics inherited from the validated substrate implementation unless separately changed during instrumentation and frozen before confirmatory sealing.

## Critical causal isolation: run producers once

The producer population is not rerun separately for P/S/G/R.

For each research case, producers receive their frozen source bundles once and emit a **canonical epistemic event log**. That immutable log is hashed and replayed into all four substrate adapters.

This prevents stochastic producer variation from becoming a hidden treatment. Across P/S/G/R, the deposited observations are byte-identical; only representation, retrieval, relational structure, and field dynamics differ.

## Canonical epistemic event

Every producer observation contains at least:

- event ID;
- case ID;
- producer ID;
- source ID and source SHA-256;
- subject, predicate, object;
- calibrated confidence in `[0,1]`;
- timezone-aware observation timestamp.

Optional fields include source locator, support/contradiction links, uncertainty text, and non-treatment metadata.

The canonical event log is substrate-neutral. No field activation, graph centrality, retrieval score, arm name, or evaluator outcome may be written by producers.

Instrumentation artifacts persist the complete canonical event-log payload as well as its SHA-256 so the evidence can be independently reconstructed and re-hashed.

## Corpus and temporal evidence semantics

Evidence is naturalistic but frozen. Confirmatory execution will have no live-web access.

Eligible source families include technical documentation, standards, papers, changelogs, incident reports, public filings, and other human-authored primary or high-quality secondary documents that can be redistributed or referenced under the project data policy.

Every source is stored or snapshotted with a cryptographic digest. Every case has a manifest containing source IDs, hashes, provenance, acquisition metadata, and the producer allocation plan.

For prospective temporal cases, `evidence_observed_at` separates the time represented by an evidence state from the time the bytes were acquired. Historical manifests that omit the field continue to use `acquired_at`, preserving their canonical mappings and hashes.

Cases should include realistic epistemic difficulty: stale evidence, contradictions, duplicates, recent incorrect claims, and facts distributed across sources. No producer may receive all preregistered required evidence sources.

When a case depends on an active contradiction or distractor producer, it may prospectively declare `minimum_events_per_producer`. The instrumentation runner checks this floor on the canonical producer log **before substrate replay or evaluator execution**.

When a case is intended to test temporal contradiction resolution, it may prospectively declare `minimum_temporal_conflict_keys`. Before replay, the canonical producer log must contain at least that many exact cross-producer, cross-time `(subject,predicate)` keys with differing objects. A document-level contradiction that does not survive stochastic producer normalization as the same claim key is therefore not allowed to masquerade as a treatment test.

Both safeguards are optional and absent from historical manifests, preserving historical hashes.

## Pre-replay gate audit retention

Calibration 007 showed that a valid pre-replay gate abort could lose the exact rejected producer log because the runner raised before the CLI wrote its output and the workflow uploaded artifacts only on success.

Prospectively, pre-replay producer-deposit or temporal-conflict failures raise a typed instrumentation gate error carrying an audit payload. The CLI writes that payload before returning a failing exit code. It records the canonical event log and hash, producer counts, gate diagnostics, `replay_attempted: false`, `evaluator_execution_attempted: false`, empty evaluator-model/draw fields, and the non-inferential/confirmatory-false boundary. Calibration workflows upload available gate evidence with `if: always()`.

This repair changes observability only; it does not relax a gate or create a treatment outcome from a failed pre-replay case.

## Cohorts

- **Instrumentation:** up to 24 cases. These may be inspected and used to repair mechanical failures and calibrate benchmark feasibility/difficulty.
- **Confirmatory:** 96 held-out cases. These remain inaccessible until protocol, source manifest, model policy, prompts, generation parameters, budgets, scoring code, and analysis are frozen.

Instrumentation outcomes are non-inferential and cannot be pooled into confirmatory inference.

The instrumentation code path rejects any manifest containing a confirmatory case. Workflows additionally reject confirmatory material by filename/stage guards and emit `confirmatory_access: false` and `confirmatory_cases_evaluated: false` evidence.

## Agents and provider identity

Producer and evaluator model identities are frozen only at the confirmatory seal. The experiment records both requested and provider-returned model identities wherever the provider exposes them.

Current Z.AI instrumentation requests `glm-5.1`, while successful artifacts report `glm-5.2` as the served producer/evaluator model. This mismatch is retained as audit evidence; confirmatory execution must enforce an explicit sealed policy on the **returned** identity rather than trusting the requested string alone.

Producer agents receive the research question as a research brief plus only their assigned frozen sources. They do **not** receive accepted answers, semantic scoring groups/slots, forbidden terms, or required-source labels. Their output is limited to source-grounded atomic events using the frozen relation ontology.

Producer-local conversational state, scratchpads, tool state, and transient memory are discarded after the canonical event log is created.

## Evaluator access boundary

Evaluators receive the held-out question and a substrate-backed retrieval interface only. They cannot read the raw corpus or producer state.

Two common tools are available in every arm:

1. `list_epistemic_subjects` — returns only normalized **subject** names present in deposited events and reveals no objects/answers;
2. `retrieve_epistemic_events(subject, predicate)` — retrieves arm-specific deposited evidence under the common retrieval policy.

The subject-list tool prevents arbitrary entity spelling from dominating exact retrieval while avoiding object/answer leakage.

Each case/arm receives five independent evaluator draws. The evaluator returns a structured answer, confidence, and cited event IDs.

## Frozen instrumentation resource controls

The common evaluator controls are:

- 12 retrieval-operation units per factual retrieval call;
- **24 total retrieval-operation units per evaluator answer**;
- **8 tool rounds per evaluator answer**;
- subject discovery is zero-cost;
- when either the operation ceiling or tool-round ceiling is reached, factual tools are disabled and the evaluator must finalize from evidence already returned.

Mechanical repairs changed only boundary finalization/transport behavior. They did not increase the 24-operation or 8-round ceilings.

Z.AI transport retries are explicit and bounded. Only transient business codes 1302/1305 are retried with bounded exponential backoff; quota, subscription, and policy-limit failures stop immediately. SDK-internal retries are disabled inside that wrapper so retry behavior is auditable.

## Primary endpoint and scoring

The single primary endpoint is **post-agent task accuracy**: correctness on the held-out task after all producer-local state has been destroyed.

Scoring is deterministic and arm-blind.

Historical cases frozen with accepted-answer strings retain normalized whole-string membership scoring. Calibration 003 demonstrated that whole-string equality is brittle for multi-value naturalistic tasks. Calibration 005 then showed that unordered bag-of-terms semantic groups can also misclassify a contextually correct boolean such as `No` when the frozen lexical requirement is `non-mutating`.

Prospectively, multi-value cases may freeze ordered `required_slots`. The evaluator answer must contain the exact number of semicolon-delimited slots, and each slot is evaluated only against its preregistered acceptable alternatives. Optional forbidden contradictory terms remain global. Historical `required_groups` cases retain their original behavior and canonical mappings.

No historical case is retroactively rescored for its primary outcome; diagnostic audits are reported separately.

Using a single primary endpoint avoids the endpoint dependence observed in Experiments 138–141.

## Secondary endpoints

Secondary diagnostics include evidence-path F1, provenance precision/recall, contradiction-resolution accuracy, unsupported-synthesis rate, bridge recovery, calibration Brier score, retrieval operation units, token use, and latency.

A non-empty answer with no valid deposited citation support is explicitly counted as **unsupported synthesis**, even when the answer text happens to match the accepted answer. Raw accuracy therefore cannot conceal completely unsupported success.

Secondary outcomes may explain mechanisms but cannot rescue a failed primary result. The repeated retrieval-efficiency pattern observed during instrumentation remains secondary/mechanistic evidence and is not promoted to a new primary endpoint after observing outcomes.

## Planned contrasts

1. S − P
2. G − S
3. R − G
4. R − P

The scientific priorities are **R − G**, testing incremental field value beyond a static graph, and **R − P**, testing total substrate value.

The provisional minimum effects frozen at scaffold creation are:

- R − G: at least **+0.03 absolute**;
- R − P: at least **+0.08 absolute**.

These thresholds may be changed only during instrumentation and before the confirmatory corpus is sealed; any change must be documented as a protocol revision without access to confirmatory outcomes. Observed instrumentation outcomes alone are not a reason to tune them.

## Statistical plan

Cases are the independent experimental units. Evaluator draws are nested repeated measurements within case/arm and must not be treated as independent cases.

The analysis is paired by case, uses a 95% confidence interval with 10,000 bootstrap resamples, a 100,000-resample paired randomization procedure where applicable, and Holm family-wise correction across the planned primary contrasts at alpha 0.05.

The final implementation may use an explicitly preregistered hierarchical estimator to model evaluator stochasticity; if adopted, it must be frozen before confirmatory sealing.

## Hard gates

A confirmatory result is admissible only if:

- canonical event-log hashes are identical across all four arms for each case;
- the full canonical event log is retained in the evidence artifact;
- evaluator model, prompt, context policy, and resource budget are identical across arms;
- provider-returned model identity satisfies the sealed model policy;
- producer-local state is unavailable after deposition;
- no live web is available during substrate evaluation;
- no mutable cross-arm state is reused;
- event provenance completeness is at least 0.99;
- unsupported synthesis is at most 0.05;
- the confirmatory corpus and source manifest hashes match the sealed manifest; and
- no treatment, metric, scoring, or analysis parameter changes after unsealing.

## Instrumentation chronology

### Pilot 001 — Python packaging

Run `31608304587`. P/S/G/R all scored 5/5. The case validated the full stochastic pipeline but was ceiling-saturated on primary accuracy.

Detailed record: `docs/llm-epistemic-substrate-142-145-pilot-results.md`.

### Calibration 002 — Python annotations

Run `31617588775`. P scored 4/5; S/G/R scored 5/5. Mean retrieval units were P 23.4, S 24.0, G 15.8, R 11.8. R and G remained tied on accuracy.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-002-results.md`.

### Calibration 003 — Rust 2024

Successful v2 run `31620858330`. Frozen whole-string scorer: P 5/5, S 3/5, G 2/5, R 4/5. Deterministic diagnostic semantic completeness was P 5/5, S 3/5, G 5/5, R 5/5; the G/R misses were punctuation variants. S's two incomplete draws were genuine resource-exhaustion failures. The historical score remains frozen.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-003-results.md`.

### Calibration 004 — Go toolchain

Successful v2 run `31624101126`. All arms scored 5/5. Mean retrieval units were P 20.4, S 18.6, G 7.8, R 7.0. The intended fourth-source distractor produced zero events, motivating the prospective producer-deposit floor.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-004-results.md`.

### Calibration 005 — Kubernetes PSP → PSA

Successful run `31631639325`. Frozen unordered semantic score: P 1/5, S 0/5, G 2/5, R 2/5. Audit showed a contextual-boolean scoring miss (`No` vs `non-mutating`); ordered-slot diagnostic completeness was P 5/5, S 1/5, G 5/5, R 5/5. S exhausted all 24 units in every draw and returned four empty answers.

All four producers deposited, including 34 stale PSP-era events, but the log did not contain the intended exact stale/current opposing-value claim. This motivated ordered slot scoring and the temporal-conflict-key floor.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-005-results.md`.

### Calibration 006 — PostgreSQL password_encryption

Successful run `31634337448`. The pre-replay gate found the intended exact `password_encryption / default_is: md5 → scram-sha-256` collision. Frozen ordered-slot primary results were P 4/5, S 4/5, G 3/5, R 5/5; mean retrieval units P 17.4, S 23.6, G 5.4, R 5.8.

This was the first prospectively frozen case-level R > G primary split (`+0.40`). However, every arm cited the current `scram-sha-256` default. G's two failures were status-wording near-misses while R selected an explicit `deprecated` event. The case therefore does not cleanly demonstrate stale-default selection as the mechanism.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-006-results.md`.

### Calibration 007 — OpenJDK keystore temporal gate abort

Workflow run `31636162375` passed implementation, source, semantic, timestamp, credential, and producer-deposit gates, then aborted before replay because the canonical producer log contained zero exact cross-time opposing claim keys while the frozen floor required one:

`temporal conflict-key floor not met before substrate replay: minimum=1; observed=0`

No P/S/G/R substrate replay or evaluator draw occurred. Calibration 007 is instrumentation-feasibility evidence, **not a null treatment result**. The failure motivated producer-log retention on future pre-replay gate aborts; the collision definition itself was not weakened.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-007-results.md`.

### Calibration 008 — PostgreSQL wal_level

Successful run `31638592754`; trigger SHA `3d0b64ce7788582b810068a1ad1c0a5d7d590dac`; artifact `9158146739`, digest `sha256:406ae3adb48279eb4c253213ddbe254afbec5dca34f1549aaaced58b5dd7f583`.

All four producers deposited. The 124-event canonical log passed the temporal gate with nine exact cross-time differing-object keys, including the intended discrete changed-value collision:

`wal_level / default_is: minimal (2016) → replica (2026)`

Frozen ordered-slot primary results:

| Arm | Correct | Mean retrieval units |
| --- | ---: | ---: |
| P | 5/5 | 23.4 |
| S | 3/5 | 24.0 |
| G | 5/5 | 8.6 |
| R | 5/5 | 7.6 |

R − G accuracy = `0.00`; R − P = `0.00`. S exhausted all 24 retrieval units in every draw and failed twice. P/G/R had provenance precision, recall, and evidence-path F1 of 1.0 in every draw and cited current required evidence; no final P/G/R answer cited the stale `minimal` event.

This is the cleanest fulfilled exact stale/current temporal design so far, and it **does not replicate** Calibration 006's R > G primary split. The artifact retains final citations but not complete evaluator retrieval traces, so it cannot prove an internal stale-rejection path for any arm.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-008-results.md`.

## Current scientific boundary

The instrumentation evidence now supports three robust design-level observations:

1. **G/R retrieval efficiency is recurring across domains.** Structured arms generally recover distributed evidence with far fewer retrieval-operation units than P/S. In Calibration 008, G used 8.6 and R 7.6 mean units versus P 23.4 and S 24.0.
2. **S is repeatedly resource-fragile on harder logs.** It frequently approaches or exhausts the frozen 24-unit ceiling, and several genuine incomplete/empty answers have occurred at that boundary.
3. **A replicated primary R > G accuracy effect is not established.** Calibration 006 produced a frozen +0.40 case-level split, but its proximate failure mechanism was semantic precision; Calibration 008 instantiated the intended exact temporal conflict cleanly and produced a 5/5 vs 5/5 tie.

The campaign has therefore crossed an important instrumentation boundary: exact temporal contradiction is feasible under the frozen producer/event contract, and continuing to redesign treatment/scoring parameters in response to case outcomes would increasingly risk outcome-driven tuning.

The next step should be prospective protocol finalization rather than chasing another favorable R > G calibration. Before confirmatory material is created, the project should freeze:

- returned-model identity policy;
- exact prompt/provider/generation policy;
- all resource ceilings and retry behavior;
- scoring contract and semantic-slot conventions;
- confirmatory source/case construction procedure;
- statistical estimator and multiplicity handling;
- instrumentation stopping rule / any remaining feasibility-only sample; and
- immutable confirmatory manifest/seal procedure.

The primary endpoint remains post-agent task accuracy. Retrieval efficiency remains secondary/mechanistic; it is not promoted to primary after observing instrumentation results.

No confirmatory case may be opened until these choices are frozen.
