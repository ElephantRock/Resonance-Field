# LLM Epistemic Substrate Replication — Experiments 142–145

## Status

Instrumentation only. One complete stochastic pilot has executed; it is non-inferential and ceiling-saturated on primary accuracy. The confirmatory corpus remains unsealed and inaccessible.

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

Evidence is naturalistic but frozen. Confirmatory execution has no live-web access.

Eligible source families include technical documentation, standards, papers, changelogs, incident reports, public filings, and other human-authored primary or high-quality secondary documents that can be redistributed or referenced under the project’s data policy.

Every source is stored or snapshotted with a cryptographic digest. Every case has a manifest containing source IDs, hashes, provenance, acquisition metadata, and the producer allocation plan.

Cases must include realistic epistemic difficulty: stale evidence, contradictions, duplicates, recent incorrect claims, and facts distributed across sources. A case is invalid if one producer’s assigned bundle is sufficient to answer the held-out task alone.

## Cohorts

- **Instrumentation:** up to 24 cases. These may be inspected and used to repair mechanical failures and calibrate benchmark difficulty.
- **Confirmatory:** 96 held-out cases. These remain inaccessible until the protocol, source manifest, model identities, prompts, generation parameters, budgets, scoring code, and analysis are frozen.

Instrumentation outcomes are non-inferential and cannot be pooled into confirmatory inference.

The instrumentation code path rejects any manifest containing a confirmatory case. Current workflows additionally reject confirmatory material by filename/stage guards and emit `confirmatory_access: false` and `confirmatory_cases_evaluated: false` evidence.

## Agents and provider identity

Producer and evaluator model identities are frozen only at the confirmatory seal. The experiment records both requested and provider-returned model identities wherever the provider exposes them.

A confirmatory workflow must reject a returned identity that violates the sealed model policy. Requested model strings alone are insufficient evidence of the model actually served.

Producer agents receive the research question as a research brief plus only their assigned frozen sources. They do **not** receive accepted answers or required-source labels. Their output is limited to source-grounded atomic events using the frozen relation ontology.

Producer-local conversational state, scratchpads, tool state, and transient memory are discarded after the canonical event log is created.

## Evaluator access boundary

Evaluators receive the held-out question and a substrate-backed retrieval interface only. They cannot read the raw corpus or producer state.

Two common tools are available in every arm:

1. `list_epistemic_subjects` — returns only normalized **subject** names present in deposited events and reveals no objects/answers;
2. `retrieve_epistemic_events(subject, predicate)` — retrieves arm-specific deposited evidence under the common retrieval policy.

The subject-list tool prevents arbitrary entity spelling from dominating exact retrieval while avoiding object/answer leakage.

Each case/arm receives five independent evaluator draws. The evaluator must return a structured answer, confidence, and cited event IDs. For multi-value questions, the answer field must contain only requested values in question order separated by `; `, with no prose or labels.

## Primary endpoint

The single primary endpoint is **post-agent task accuracy**: correctness on the held-out task after all producer-local state has been destroyed.

Answers are scored deterministically against accepted answer strings frozen in the case manifest. Scoring is arm-blind.

Using a single primary endpoint avoids the endpoint dependence observed in Experiments 138–141.

## Secondary endpoints

Secondary diagnostics include evidence-path F1, provenance precision/recall, contradiction-resolution accuracy, unsupported-synthesis rate, bridge recovery, calibration Brier score, retrieval operation units, token use, and latency.

A non-empty answer with no valid deposited citation support is explicitly counted as **unsupported synthesis**, even when the answer text happens to match the accepted answer. Raw accuracy therefore cannot conceal unsupported success.

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

## First stochastic pilot

The first complete stochastic pilot, `instr-python-packaging-001`, executed successfully in workflow run `31608304587` after a transport-level structured-output defect was repaired and regression-tested.

All 20 evaluator executions were correct: 5/5 for P, S, G, and R. Unsupported synthesis was zero in every draw. The case therefore validates the complete stochastic/post-agent transfer machinery but is **ceiling-saturated** and does not estimate a primary accuracy treatment effect.

Graph and Resonance used substantially fewer retrieval-operation units than Pile and Shared Memory on this case, but this is a one-case secondary instrumentation observation only.

The workflow requested `glm-5.1`; all evaluator completions in the successful artifact reported `glm-5.2`. This requested/returned identity mismatch must be resolved before confirmatory model sealing.

Detailed results and audit identifiers are in `docs/llm-epistemic-substrate-142-145-pilot-results.md`.

## Current engineering/scientific boundary

Before the instrumentation cohort expands, the project should:

1. use a provider endpoint/plan whose terms authorize this experiment runner;
2. freeze and enforce provider-returned model identity;
3. retain complete canonical producer event logs in artifacts;
4. curate a harder difficulty-calibration tranche containing contradictions, stale/current evidence, multi-hop composition, plausible distractors, and at least three distributed required facts; and
5. freeze a total per-answer retrieval-operation ceiling rather than relying solely on a per-call ceiling.

The current Z.AI Coding Plan endpoint is not being used for further custom paid experiment calls pending an authorized provider path. No confirmatory case may be opened during this work.
