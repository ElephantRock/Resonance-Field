# LLM Epistemic Substrate Replication — Experiments 142–145

## Status

Instrumentation scaffold only. The confirmatory corpus is not sealed and no confirmatory case may be evaluated at this stage.

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

Every producer observation must contain at least:

- event ID;
- case ID;
- producer ID;
- source ID and source SHA-256;
- subject, predicate, object;
- calibrated confidence in `[0,1]`;
- timezone-aware observation timestamp.

Optional fields include source locator, support/contradiction links, uncertainty text, and non-treatment metadata.

The canonical event log is substrate-neutral. No field activation, graph centrality, retrieval score, arm name, or evaluator outcome may be written by producers.

## Corpus

Evidence is naturalistic but frozen. Confirmatory execution has no live-web access.

Eligible source families include technical documentation, standards, papers, changelogs, incident reports, public filings, and other human-authored primary or high-quality secondary documents that can be redistributed or referenced under the project’s data policy.

Every source is stored or snapshotted with a cryptographic digest. Every case has a manifest containing source IDs, hashes, provenance, acquisition metadata, and the producer allocation plan.

Cases must include realistic epistemic difficulty: stale evidence, contradictions, duplicates, recent incorrect claims, and facts distributed across sources. A case is invalid if one producer’s assigned bundle is sufficient to answer the held-out task alone.

## Cohorts

- **Instrumentation:** 24 cases. These may be inspected and used to repair mechanical failures.
- **Confirmatory:** 96 held-out cases. These remain inaccessible until the protocol, source manifest, model identities, prompts, generation parameters, budgets, scoring code, and analysis are frozen.

Instrumentation outcomes are non-inferential and cannot be pooled into confirmatory inference.

## Agents

Producer and evaluator model identities are frozen at the confirmatory seal. Their system prompts are stored by SHA-256. Generation parameters, tool budgets, token ceilings, and context construction are identical across arms.

Each case/arm receives five independent evaluator draws. Arm order is randomized. Scoring is blinded to arm identity.

Producer-local conversational state, scratchpads, tool state, and transient memory are destroyed before substrate evaluation. Evaluators receive only the substrate representation and the frozen evaluation task.

## Primary endpoint

The single primary endpoint is **post-agent task accuracy**: correctness on the held-out task after all producer-local state has been destroyed.

Using a single primary endpoint avoids the endpoint dependence observed in Experiments 138–141.

## Secondary endpoints

Secondary diagnostics include evidence-path F1, provenance precision/recall, contradiction-resolution accuracy, unsupported-synthesis rate, bridge recovery, calibration Brier score, retrieval operation units, token use, and latency.

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
- evaluator model, prompt, context policy, and budget are identical across arms;
- producer-local state is unavailable after deposition;
- no live web is available during substrate evaluation;
- no mutable cross-arm state is reused;
- event provenance completeness is at least 0.99;
- unsupported synthesis is at most 0.05;
- the confirmatory corpus and source manifest hashes match the sealed manifest; and
- no treatment, metric, scoring, or analysis parameter changes after unsealing.

## Current engineering boundary

This branch currently establishes the campaign configuration and substrate-neutral epistemic-event schema. Next, instrumentation work must implement:

1. corpus/source manifests and hash validation;
2. producer runner that emits canonical event logs;
3. deterministic replay adapters from one event log into P/S/G/R;
4. evaluator runner with randomized arm order and repeated draws;
5. blinded scoring and provenance verification; and
6. instrumentation-only workflow that cannot access the 96 confirmatory cases.

Only after all six layers are green may a separate seal commit identify the confirmatory corpus, model IDs, prompt hashes, and final inference procedure.
