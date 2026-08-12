# LLM Epistemic Substrate Replication — Experiments 142–145

## Status

Instrumentation only. One stochastic pilot and three harder multi-domain calibration cases have executed. Calibration outcomes are non-inferential and are used only to validate mechanics, scoring, resource controls, and benchmark difficulty. The 96 confirmatory cases remain uncreated, unobserved, and inaccessible.

The current instrumentation evidence shows a repeated retrieval-efficiency advantage for structured G/R substrates over P/S, but **does not establish a replicated primary accuracy advantage for R over G**.

## Objective

Replicate Experiments 138–141 under substantially stronger external-validity conditions: naturalistic human-authored evidence, stochastic LLM producer agents, and stochastic LLM evaluator agents.

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

## Corpus

Evidence is naturalistic but frozen. Confirmatory execution will have no live-web access.

Eligible source families include technical documentation, standards, papers, changelogs, incident reports, public filings, and other human-authored primary or high-quality secondary documents that can be redistributed or referenced under the project data policy.

Every source is stored or snapshotted with a cryptographic digest. Every case has a manifest containing source IDs, hashes, provenance, acquisition metadata, and the producer allocation plan.

Cases should include realistic epistemic difficulty: stale evidence, contradictions, duplicates, recent incorrect claims, and facts distributed across sources. No producer may receive all preregistered required evidence sources.

When a case depends on an active contradiction or distractor producer, the case may prospectively declare `minimum_events_per_producer`. The instrumentation runner checks this floor on the canonical producer log **before substrate replay or evaluator execution**. The field is optional and absent from historical manifests, preserving their canonical mappings and hashes.

## Cohorts

- **Instrumentation:** up to 24 cases. These may be inspected and used to repair mechanical failures and calibrate benchmark difficulty.
- **Confirmatory:** 96 held-out cases. These remain inaccessible until the protocol, source manifest, model policy, prompts, generation parameters, budgets, scoring code, and analysis are frozen.

Instrumentation outcomes are non-inferential and cannot be pooled into confirmatory inference.

The instrumentation code path rejects any manifest containing a confirmatory case. Workflows additionally reject confirmatory material by filename/stage guards and emit `confirmatory_access: false` and `confirmatory_cases_evaluated: false` evidence.

## Agents and provider identity

Producer and evaluator model identities are frozen only at the confirmatory seal. The experiment records both requested and provider-returned model identities wherever the provider exposes them.

Current Z.AI instrumentation requests `glm-5.1`, while successful artifacts have reported `glm-5.2` as the served producer/evaluator model. This mismatch is retained as audit evidence; confirmatory execution must enforce an explicit sealed policy on the **returned** identity rather than trusting the requested string alone.

Producer agents receive the research question as a research brief plus only their assigned frozen sources. They do **not** receive accepted answers, semantic scoring groups, forbidden terms, or required-source labels. Their output is limited to source-grounded atomic events using the frozen relation ontology.

Producer-local conversational state, scratchpads, tool state, and transient memory are discarded after the canonical event log is created.

## Evaluator access boundary

Evaluators receive the held-out question and a substrate-backed retrieval interface only. They cannot read the raw corpus or producer state.

Two common tools are available in every arm:

1. `list_epistemic_subjects` — returns only normalized **subject** names present in deposited events and reveals no objects/answers;
2. `retrieve_epistemic_events(subject, predicate)` — retrieves arm-specific deposited evidence under the common retrieval policy.

The subject-list tool prevents arbitrary entity spelling from dominating exact retrieval while avoiding object/answer leakage.

Each case/arm receives five independent evaluator draws. The evaluator returns a structured answer, confidence, and cited event IDs.

## Frozen instrumentation resource controls

The current common evaluator controls are:

- 12 retrieval-operation units per factual retrieval call;
- **24 total retrieval-operation units per evaluator answer**;
- **8 tool rounds per evaluator answer**;
- subject discovery is zero-cost;
- when either the operation ceiling or tool-round ceiling is reached, factual tools are disabled and the evaluator must finalize from evidence already returned.

Mechanical repairs introduced during Calibration 002 and Calibration 004 changed only boundary finalization behavior. They did not increase the 24-operation or 8-round ceilings.

Z.AI transport retries are explicit and bounded. Only transient business codes 1302/1305 are retried with bounded exponential backoff; quota, subscription, and policy-limit failures stop immediately. SDK-internal retries are disabled inside that wrapper so retry behavior is auditable.

## Primary endpoint

The single primary endpoint is **post-agent task accuracy**: correctness on the held-out task after all producer-local state has been destroyed.

Scoring is deterministic and arm-blind.

Historical cases that were frozen with accepted-answer strings retain normalized whole-string membership scoring. Calibration 003 demonstrated that this is too brittle for multi-value naturalistic tasks because semantically identical punctuation variants can be misclassified.

Prospectively, a case may instead freeze `semantic_answer_requirements` containing:

- required groups of alternative acceptable terms; and
- optional forbidden contradictory terms.

A semantic-scored answer is correct only when every required group is represented and no forbidden term is present. The requirements are frozen in the case manifest before execution and are never shown to producers or evaluators.

Calibration 004 was the first case executed under this prospective semantic contract.

Using a single primary endpoint avoids the endpoint dependence observed in Experiments 138–141.

## Secondary endpoints

Secondary diagnostics include evidence-path F1, provenance precision/recall, contradiction-resolution accuracy, unsupported-synthesis rate, bridge recovery, calibration Brier score, retrieval operation units, token use, and latency.

A non-empty answer with no valid deposited citation support is explicitly counted as **unsupported synthesis**, even when the answer text happens to match the accepted answer. Raw accuracy therefore cannot conceal completely unsupported success.

Secondary outcomes may explain mechanisms but cannot rescue a failed primary result.

## Planned contrasts

1. S − P
2. G − S
3. R − G
4. R − P

The scientific priorities are **R − G**, testing incremental field value beyond a static graph, and **R − P**, testing total substrate value.

The provisional minimum effects frozen at scaffold creation are:

- R − G: at least **+0.03 absolute**;
- R − P: at least **+0.08 absolute**.

These thresholds may be changed only during instrumentation and before the confirmatory corpus is sealed; any change must be documented as a protocol revision without access to confirmatory outcomes.

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

Successful run `31617588775`. P scored 4/5; S/G/R scored 5/5. Mean retrieval units were P 23.4, S 24.0, G 15.8, R 11.8. This is the only current harder case with an observed primary accuracy separation between an unstructured arm and structured arms. R and G remained tied on accuracy.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-002-results.md`.

### Calibration 003 — Rust 2024

Successful run `31620858330`. The frozen whole-string scorer misclassified semantically correct punctuation variants in G/R; deterministic diagnostic semantic completeness was P 5/5, S 3/5, G 5/5, R 5/5. S's two incomplete draws were genuine resource-exhaustion failures. Calibration 003 remains frozen with its original raw score plus diagnostic audit and is not retroactively rescored.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-003-results.md`.

### Calibration 004 — Go toolchain selection

Successful v2 run `31624101126`. This was the first prospectively semantic-scored case. All arms scored 5/5. Mean retrieval units were P 20.4, S 18.6, G 7.8, R 7.0. P/G/R had evidence-path F1 and provenance recall 1.0; S mean evidence-path F1 was 0.92 and provenance recall 0.867.

The intended fourth-source distractor produced zero events, so this case did not test active distractor competition after deposition. That finding motivated the prospective producer-deposit floor.

Detailed record: `docs/llm-epistemic-substrate-142-145-calibration-004-results.md`.

## Current scientific boundary

The multi-domain instrumentation evidence supports a repeated **retrieval-efficiency mechanism**: G/R generally recover distributed evidence using substantially fewer operation units than P/S. It does not yet support a replicated primary accuracy claim for R over G.

The next calibration cases should therefore:

1. preserve the 24-operation and 8-round ceilings;
2. use prospective semantic scoring for multi-value answers;
3. preregister a nonzero producer-deposit floor when contradiction/distractor activity is part of the design;
4. include active stale/current or contradictory claims rather than merely adjacent distractor documents;
5. vary domain and vocabulary beyond Python, Rust, and Go; and
6. retain complete canonical event logs plus requested/returned model identities.

No confirmatory case may be opened until instrumentation mechanics, model-identity policy, scoring, and analysis are frozen.
