# Experiments 142–145 — Confirmatory Design Adequacy Gate

Date: 2026-08-12

## Status

Pre-confirmatory design analysis only. No confirmatory case has been created, opened, or evaluated.

This record identifies a blocking mismatch between the scaffolded confirmatory sample size (`96` cases), the provisional minimum incremental effect for R−G (`+0.03` absolute accuracy), and the planned family-wise multiplicity control.

It does **not** change the primary endpoint, treatment definitions, minimum effects, or confirmatory case count. Those remain unchanged in the campaign config until a prospective protocol revision resolves this gate.

## Why this check is necessary

Cases are the independent experimental units. Five evaluator draws within a case are nested repeated measurements; they do not turn 96 cases into 480 independent cases.

The scaffold currently specifies:

- 96 confirmatory cases;
- primary endpoint: post-agent task accuracy;
- four planned paired contrasts;
- Holm family-wise alpha 0.05;
- provisional minimum R−G effect: `0.03`;
- provisional minimum R−P effect: `0.08`.

A confirmatory design should have a defensible probability of resolving the minimum effect it claims to target. Sealing 96 cases without checking that relationship risks a formally correct but predictably underpowered experiment.

## Planning quantity

For this adequacy check only, let `D_i` be the case-level R−G accuracy difference, with each arm's case accuracy equal to the mean of its five evaluator draws. The approximate normal-theory sample-size relation for a paired mean is:

`n ≈ ((z_alpha + z_power) * sigma_D / delta)^2`

where:

- `delta` is the target paired mean difference;
- `sigma_D` is the standard deviation of case-level paired differences;
- `z_power = 0.8416` for 80% power;
- a conservative Holm first-step bound across four contrasts uses two-sided `alpha = 0.05 / 4 = 0.0125`, giving `z_alpha ≈ 2.4977`.

This is a planning approximation, not the confirmatory estimator. The sealed confirmatory analysis remains paired bootstrap/randomization unless prospectively revised.

## Instrumentation variance estimate

Instrumentation is explicitly allowed to calibrate benchmark feasibility and variance before the confirmatory seal. To avoid contaminating this estimate with known primary-scoring defects, use only completed cases whose frozen primary scorer is not known to be mechanically invalid for the task:

- Pilot 001: R−G = `0.00`;
- Calibration 002: R−G = `0.00`;
- Calibration 004: R−G = `0.00`;
- Calibration 006: R−G = `+0.40`;
- Calibration 008: R−G = `0.00`.

Calibrations 003 and 005 are excluded from this variance estimate because their frozen primary scorers were later shown to misclassify semantically valid answers. Calibration 007 has no treatment outcome.

For the five eligible case-level differences above:

- sample mean = `0.08` — **not used for planning the target effect**;
- sample standard deviation `sigma_D ≈ 0.1789` — used only as a variance estimate.

The estimate is necessarily uncertain because it is based on five cases. The sensitivity analysis below therefore also includes larger planning SD values.

## What 96 cases can resolve

With `n = 96`, four-contrast Holm worst-case alpha, 80% nominal power, and `sigma_D = 0.1789`, the normal approximation gives a detectable paired effect of approximately:

`delta ≈ 0.061`

or **6.1 percentage points**.

Thus the existing 96-case scaffold is approximately sized for a 6-pp R−G effect under the observed planning variance, not the provisional 3-pp effect.

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

The current five-case variance estimate lies near the 397-case row. A round target of **512 cases** would provide margin up to approximately `sigma_D = 0.20` under this planning approximation and preserve a clean power-of-two / balanced-strata design. This is the recommended high-rigor path if the scientific requirement remains sensitivity to a 3-pp R−G effect.

This recommendation is based on variance/precision, not on whether the observed instrumentation mean favored R.

## Two admissible pre-seal resolutions

The campaign must choose one path **before confirmatory case construction**:

### A. Preserve the 3-pp R−G scientific target

Increase the confirmatory case count and freeze a formal simulation-based power analysis under the final estimator. The current planning calculation recommends evaluating a design in the vicinity of **512 independent cases**, with domain/case-type strata specified prospectively.

### B. Preserve the 96-case confirmatory budget

Prospectively revise the minimum incremental R−G effect to a value the 96-case design can resolve, approximately **6–7 pp** under the current planning variance and multiplicity assumptions, then validate that threshold with simulation under the final estimator.

Changing the minimum effect for this reason is a design-adequacy revision, not an outcome-driven attempt to rescue a specific observed arm result. It must nevertheless be explicitly versioned before any confirmatory content is created.

## What is not admissible

Do not:

- treat the five evaluator draws as independent cases to claim a larger effective `n`;
- reduce multiplicity correction after seeing confirmatory outcomes;
- use the instrumentation mean R−G effect as the target alternative;
- choose the final case count after inspecting confirmatory data;
- create a 96-case corpus first and decide later whether it was large enough;
- promote retrieval-operation efficiency to primary because accuracy requires a larger sample.

## Required next implementation

Before the confirmatory seal, add a deterministic power/precision simulation tied to the final paired/hierarchical estimator and freeze:

1. target R−G and R−P minimum effects;
2. confirmatory case count;
3. number of evaluator draws per case/arm;
4. multiplicity family and alpha allocation;
5. assumed case-level heterogeneity / stochastic-draw model used for power;
6. minimum evaluable-case rule if arm-independent pre-replay gates fail after sealing.

The protocol must then record a single sample-size decision and its rationale before any of the held-out source bundles are created.

## Current gate

Until this adequacy issue is resolved:

- campaign config remains at the instrumentation/pre-confirmatory boundary;
- the existing `confirmatory_case_count: 96` and `minimum_incremental_effect_r_minus_g: 0.03` remain provisional scaffold values;
- no confirmatory corpus may be created or sealed;
- no additional outcome-bearing calibration may be used to tune the choice.
