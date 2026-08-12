# Experiments 142–145 — Confirmatory Design Adequacy Gate

Date: 2026-08-12

## Status

**Resolved by Protocol Revision 001.** No confirmatory case has been created, opened, or evaluated.

This record identified a mismatch between the original scaffolded confirmatory sample size (`96` cases), the provisional minimum incremental effect for R−G (`+0.03` absolute accuracy), and the planned family-wise multiplicity control.

Protocol Revision 001 resolves the mismatch by increasing the planned confirmatory cohort to **512 independent cases** while preserving the 3-pp R−G target, the primary endpoint, five nested evaluator draws, the treatment definitions, resource ceilings, and Holm family-wise control.

Revision record: `docs/llm-epistemic-substrate-142-145-protocol-revision-001-sample-size.md`.

## Why this check was necessary

Cases are the independent experimental units. Five evaluator draws within a case are nested repeated measurements; they do not turn 96 cases into 480 independent cases or 512 cases into 2,560 independent cases.

The original scaffold specified:

- 96 confirmatory cases;
- primary endpoint: post-agent task accuracy;
- four planned paired contrasts;
- Holm family-wise alpha 0.05;
- provisional minimum R−G effect: `0.03`;
- provisional minimum R−P effect: `0.08`.

A confirmatory design should have a defensible probability of resolving the minimum effect it claims to target. Sealing 96 cases without checking that relationship would risk a formally correct but predictably underpowered experiment.

## Planning quantity

For this adequacy check only, let `D_i` be the case-level R−G accuracy difference, with each arm's case accuracy equal to the mean of its five evaluator draws. The approximate normal-theory sample-size relation for a paired mean is:

`n ≈ ((z_alpha + z_power) * sigma_D / delta)^2`

where:

- `delta` is the target paired mean difference;
- `sigma_D` is the standard deviation of case-level paired differences;
- `z_power = 0.8416` for 80% power;
- a conservative Holm first-step bound across four contrasts uses two-sided `alpha = 0.05 / 4 = 0.0125`, giving `z_alpha ≈ 2.4977`.

This is a planning approximation, not the confirmatory estimator. The confirmatory implementation now explicitly reduces nested draws to case-level arm means, bootstraps cases, performs paired within-case arm-label randomization, and Holm-adjusts the four preregistered contrasts.

Implementation: `src/resonance/experiments/llm_epistemic_confirmatory_analysis.py`.

## Instrumentation variance estimate

Instrumentation is explicitly allowed to calibrate benchmark feasibility and variance before the confirmatory seal. To avoid contaminating this estimate with known primary-scoring defects, only completed cases whose frozen primary scorer is not known to be mechanically invalid for the task were used:

- Pilot 001: R−G = `0.00`;
- Calibration 002: R−G = `0.00`;
- Calibration 004: R−G = `0.00`;
- Calibration 006: R−G = `+0.40`;
- Calibration 008: R−G = `0.00`.

Calibrations 003 and 005 are excluded because their frozen primary scorers were later shown to misclassify semantically valid answers. Calibration 007 has no treatment outcome.

For the five eligible case-level differences:

- sample mean = `0.08` — **not used as the target alternative**;
- sample standard deviation `sigma_D ≈ 0.1789` — used only as a variance estimate.

The variance estimate is necessarily uncertain because it is based on five cases. Sensitivity therefore includes larger planning SD values.

## What the original 96 cases could resolve

With `n = 96`, four-contrast Holm worst-case alpha, 80% nominal power, and `sigma_D = 0.1789`, the normal approximation gives a detectable paired effect of approximately:

`delta ≈ 0.061`

or **6.1 percentage points**.

Thus the original 96-case scaffold was approximately sized for a 6-pp R−G effect under the observed planning variance, not the provisional 3-pp effect.

## Cases required for a 3-pp R−G target

Approximate required independent cases at 80% power and the same conservative family-wise bound:

| Planning SD of case-level R−G | Required cases for `delta = 0.03` |
| ---: | ---: |
| 0.150 | 279 |
| 0.175 | 380 |
| 0.1789 | 397 |
| 0.200 | 496 |
| 0.225 | 628 |
| 0.250 | 775 |

The five-case variance estimate lies near the 397-case row. **512 cases** provide planning margin through approximately `sigma_D = 0.20` under this normal approximation and preserve the 3-pp scientific target.

This sample-size choice is based on variance/precision, not on whether the observed instrumentation mean favored R.

## Resolution selected

The campaign selected the higher-rigor path:

- preserve the 3-pp R−G target;
- increase the confirmatory cohort to **512 independent cases**;
- keep five evaluator draws nested within each case/arm;
- retain the four-contrast Holm family;
- implement the paired case-level confirmatory estimator before corpus construction.

The alternative—retaining 96 cases and revising the minimum R−G effect upward to approximately 6–7 pp—was not selected.

## What remains inadmissible

Do not:

- treat evaluator draws as independent cases;
- reduce multiplicity correction after seeing confirmatory outcomes;
- use the instrumentation mean R−G effect as the target alternative;
- choose or change the case count after inspecting confirmatory data;
- promote retrieval-operation efficiency to primary because accuracy requires a larger sample;
- use post-seal gate failures to replenish or replace cases without a frozen rule.

## Remaining adequacy requirement

The 512-case revision resolves the first-order normal-theory blocker, but the normal approximation is not the final power proof.

Before confirmatory sealing, add and freeze a deterministic simulation/precision check tied to the final case-level estimator and specify:

1. target R−G and R−P minimum effects;
2. 512 confirmatory cases;
3. five evaluator draws per case/arm;
4. the four-contrast Holm family and alpha 0.05;
5. the assumed case-level heterogeneity / stochastic-draw model used for power;
6. the minimum evaluable-case rule if arm-independent pre-replay gates fail after sealing.

If the prospective simulation shows 512 is inadequate under the frozen planning assumptions, the protocol must fail before confirmatory content is created. No post-hoc expansion is allowed after corpus creation or unsealing.

## Current gate

The sample-size mismatch is resolved, but confirmatory construction remains blocked until the remaining pre-confirmatory protocol choices and simulation are frozen.

Current planned values:

- `confirmatory_case_count: 512`;
- `minimum_incremental_effect_r_minus_g: 0.03`;
- `minimum_total_effect_r_minus_p: 0.08`;
- confirmatory cases sealed: false;
- confirmatory cases created: false;
- no additional outcome-bearing calibration may be used to tune these choices.
