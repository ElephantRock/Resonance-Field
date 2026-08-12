# Experiments 142–145 — Instrumentation Outcome-Tuning Stop

Date: 2026-08-12

## Decision

Calibration 008 closes **outcome-bearing treatment/scoring/resource tuning** for the stochastic Epistemic Substrate replication.

This is not the confirmatory seal. Following Protocol Revision 001, the **512 planned confirmatory cases** remain uncreated, unobserved, and inaccessible. The purpose of this record is to prevent subsequent instrumentation outcomes from being used to reshape the experiment toward a favorable arm comparison.

## Evidence at the stopping boundary

The campaign has established the mechanical capabilities needed for the intended external-validity test:

- stochastic producers can deposit one canonical source-grounded event log per case;
- the identical hashed log can be replayed into P/S/G/R;
- frozen source provenance, model identity, evaluator resource ceilings, and deterministic scoring are retained;
- active producer floors can be enforced before replay;
- evidence acquisition time can be separated from evidence-state time;
- ordered slot-aware semantic scoring avoids the known multi-value scoring failures;
- exact temporal-conflict gates can reject document-level contradictions that do not survive producer normalization;
- a clean discrete stale/current exact conflict has now survived producer normalization and executed through all four arms;
- pre-replay gate failures can now retain canonical producer evidence without creating a treatment outcome.

The primary instrumentation findings at this boundary are:

1. G/R repeatedly use materially fewer retrieval-operation units than P/S across independent domains;
2. S repeatedly reaches the frozen 24-unit budget on harder logs and has produced genuine incomplete/empty answers at the boundary;
3. Calibration 006 produced a prospectively frozen case-level R > G primary split, but its proximate failure mechanism was semantic-status precision rather than stale-default selection;
4. Calibration 008 instantiated the intended exact stale/current discrete changed-value conflict and produced P 5/5, G 5/5, R 5/5, with S 3/5;
5. therefore a primary R > G accuracy effect is **not replicated** in instrumentation.

## Frozen anti-tuning rule

From this record forward, before confirmatory unsealing:

- do not change P/S/G/R treatment definitions in response to instrumentation outcomes;
- do not increase or decrease the 12-unit per-call, 24-unit per-answer, or 8-round evaluator ceilings in response to arm performance;
- do not promote retrieval efficiency or any other observed secondary diagnostic to the primary endpoint;
- do not change semantic scoring conventions to rescue or penalize a specific observed arm result;
- do not change the provisional R−G or R−P minimum-effect thresholds merely because of observed instrumentation effect sizes;
- do not weaken producer-deposit or exact temporal-conflict gates to admit a failed case as an outcome;
- do not rerun a completed stochastic case solely to seek a more favorable draw realization;
- do not create or inspect confirmatory case contents until the remaining protocol decisions below are frozen.

Mechanical corrections remain allowed before the confirmatory seal only when they are outcome-blind, documented, regression-tested, and do not alter treatment capability or selectively benefit an arm. If a correction could affect scientific interpretation, it requires a protocol revision record before any confirmatory material is accessed.

## Pre-confirmatory decisions already resolved after this stop

Two design issues have now been prospectively resolved without confirmatory access:

1. **Confirmatory estimator:** nested evaluator draws are reduced to one arm mean per independent case; bootstrap resampling operates on cases; paired randomization swaps arm labels within case; four contrast p-values receive Holm adjustment. Implementation: `src/resonance/experiments/llm_epistemic_confirmatory_analysis.py`.
2. **Confirmatory sample size:** Protocol Revision 001 preserves the 3-pp R−G target and increases the confirmatory cohort from the original 96-case scaffold to **512 independent cases**. The revision is based on variance/precision, not on the observed mean R−G effect.

Records:

- `docs/llm-epistemic-substrate-142-145-confirmatory-design-adequacy.md`;
- `docs/llm-epistemic-substrate-142-145-protocol-revision-001-sample-size.md`.

## Remaining pre-confirmatory work

The following choices still require prospective freezing:

1. **Returned-model identity policy** — define acceptable provider-returned producer/evaluator identities and behavior on mismatch.
2. **Provider and generation policy** — exact endpoint, prompts, reasoning/generation parameters, structured-output schemas, retry policy, and state-retention policy.
3. **Case construction policy** — domain strata, evidence-source eligibility, stale/current/contradiction quotas, producer allocation constraints, and rules for source timestamps.
4. **Scoring policy** — final accepted-answer/ordered-slot conventions, forbidden-term use, provenance diagnostics, and treatment of empty/resource-boundary answers.
5. **Power/evaluable-case rule** — run the deterministic pre-seal power simulation for the 512-case design and freeze the minimum evaluable-case rule for arm-independent gate failures.
6. **Confirmatory manifest and seal procedure** — create the 512 cases only after all preceding choices are frozen, hash source/case manifests, freeze code/config/prompt/model identities, and record an immutable seal before execution.

## Permitted further instrumentation

No additional case may be used to tune treatment, scoring, resource ceilings, or minimum effects.

If further instrumentation is required before sealing, it must be declared **before execution** as one of:

- mechanical/provider compatibility validation;
- fixed-scope variance/resource estimation under already frozen controls; or
- confirmatory-pipeline dry run on non-confirmatory data.

Its purpose, case count, domain selection rule, and decision rule must be recorded prospectively. Results may reveal a mechanical impossibility that blocks sealing, but they may not be used to chase an R > G accuracy pattern.

## Confirmatory boundary

At the current pre-confirmatory boundary:

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- planned confirmatory cases: `512`
- confirmatory cases sealed: false
- confirmatory cases created: false

The next scientific milestone is a **pre-confirmatory protocol freeze**, followed by creation and cryptographic sealing of the held-out 512-case corpus. No confirmatory outcome may be generated before that seal.
