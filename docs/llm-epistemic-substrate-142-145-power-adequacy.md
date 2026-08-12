# Experiments 142–145 — Deterministic Pre-Seal Power Adequacy

Date: 2026-08-12
Status: pre-confirmatory; no confirmatory content created or accessed

## Decision

The revised design remains:

- **512** sealed independent confirmatory cases;
- **496** minimum evaluable cases;
- no post-seal case replacement;
- five evaluator draws nested within each case/arm;
- four planned contrasts in one Holm family;
- hard observed-effect gates of +3 pp for R−G and +8 pp for R−P;
- campaign PASS only if both priority contrasts also achieve Holm-adjusted p < 0.05 and paired-bootstrap lower bound > 0.

The 496 minimum-evaluable rule is the conservative first-order 80%-detection boundary for a true +3-pp R−G effect at paired SD 0.20 under the first Holm threshold. If fewer than 496 sealed cases are evaluable after arm-independent pre-replay gates, the execution is statistically **inadmissible**. Cases are not replenished after sealing.

Implementation:

- `src/resonance/experiments/llm_epistemic_power.py`
- `tests/test_llm_epistemic_power.py`
- campaign success semantics: `src/resonance/experiments/llm_epistemic_confirmatory_analysis.py`

## Planning semantics

This report deliberately separates:

1. **Detection power** — probability that a priority effect is statistically positive against zero under a conservative first-Holm-step planning threshold;
2. **Hard-gate PASS probability** — detection plus the requirement that the observed effect also meet the frozen magnitude gate.

The actual confirmatory estimator remains the frozen case-level paired randomization/bootstrap analysis with Holm adjustment. The power model is a deterministic planning approximation; it does not replace the confirmatory resampling test.

## Variance source and anti-tuning control

Only five completed instrumentation cases whose frozen primary scorer has no known mechanical defect are used for planning residual shape:

- Pilot 001;
- Calibration 002;
- Calibration 004;
- Calibration 006;
- Calibration 008.

Case-level paired differences were:

- R−G: `0.00, 0.00, 0.00, 0.40, 0.00`; sample SD `0.178885...`;
- R−P: `0.00, 0.20, 0.00, 0.20, 0.00`; sample SD `0.109545...`.

The observed means are **not used as planning alternatives**. Each vector is centered, and its two-point residual support is scaled by `sqrt(m/(m-1))` so the planning distribution preserves the sample SD rather than the smaller empirical-population SD.

The normal robustness screen separately uses paired SD **0.20** for R−G, above the eligible instrumentation estimate.

## Conservative multiplicity threshold

For planning, each priority contrast is screened against the strictest possible Holm step:

- family-wise alpha: 0.05;
- four planned contrasts;
- two-sided per-test bound: `0.05 / 4 = 0.0125`;
- corresponding normal critical value: approximately `2.4977`.

This is conservative because an actual priority contrast can receive a less stringent Holm step depending on the full ordered p-value family.

## Normal SD 0.20 adequacy screen

For a true R−G effect of +3 pp and paired SD 0.20:

| Evaluable cases | Approx. detection power |
| ---: | ---: |
| 495 | 0.7994 |
| **496** | **0.8004** |
| 512 | 0.8150 |

Therefore 496 is frozen as the minimum evaluable count. The full 512-case design supplies 16 cases of operational attrition margin while retaining the first-order 80% detection criterion at the SD 0.20 planning ceiling.

## Exact enumeration under centered empirical residual shape — 512 cases

### R − G, hard gate +0.03

| True effect | Detection power | Hard-gate PASS probability |
| ---: | ---: | ---: |
| 0.00 | 0.0046 | 0.0001 |
| **0.03** | **0.9247** | **0.4912** |
| 0.04 | 0.9984 | 0.9072 |
| 0.05 | 1.0000 | 0.9953 |
| 0.06 | 1.0000 | 1.0000 |

The +3-pp threshold row makes the statistical semantics explicit: detection power can exceed 90% while joint hard-gate PASS remains near 50% because the true effect is exactly on the observed-effect threshold.

### R − P, hard gate +0.08

| True effect | Detection power | Hard-gate PASS probability |
| ---: | ---: | ---: |
| 0.00 | 0.0065 | ~0 |
| **0.08** | **1.0000** | **0.5096** |
| 0.09 | 1.0000 | 0.9827 |
| 0.10 | 1.0000 | 1.0000 |
| 0.12 | 1.0000 | 1.0000 |

Again, ~50% hard-gate probability at the exact +8-pp threshold is expected from a symmetric threshold rule and is not an argument for moving the gate.

## Minimum-evaluable operating point — 496 cases

At the frozen attrition boundary:

### R − G

| True effect | Detection power | Hard-gate PASS probability |
| ---: | ---: | ---: |
| 0.00 | 0.0039 | 0.0002 |
| 0.03 | 0.9070 | 0.4821 |
| 0.04 | 0.9979 | 0.8862 |
| 0.05 | 1.0000 | 0.9938 |
| 0.06 | 1.0000 | 1.0000 |

### R − P

| True effect | Detection power | Hard-gate PASS probability |
| ---: | ---: | ---: |
| 0.00 | 0.0052 | ~0 |
| 0.08 | 1.0000 | 0.4951 |
| 0.09 | 1.0000 | 0.9782 |
| 0.10 | 1.0000 | 1.0000 |
| 0.12 | 1.0000 | 1.0000 |

## Campaign-level PASS without inventing cross-contrast dependence

Campaign PASS requires both priority gates. The instrumentation sample is too small to justify freezing a parametric correlation model between the future R−G and R−P estimators.

Therefore the power plan does **not** multiply the two marginal PASS probabilities or assume independence. It reports dependence-agnostic Fréchet bounds:

`max(0, P(R−G pass) + P(R−P pass) − 1) <= P(campaign pass) <= min(P(R−G pass), P(R−P pass))`.

Examples:

- At the exact hard thresholds (+3 pp R−G, +8 pp R−P), the joint PASS probability is intentionally not claimed to be 80%; the marginal gates are each near 50%.
- At +4 pp R−G and +9 pp R−P with 512 cases, the dependence-agnostic lower bound is approximately `0.9072 + 0.9827 − 1 = 0.8899`.
- At the 496-case evaluable boundary for those same effects, the lower bound is approximately `0.8862 + 0.9782 − 1 = 0.8644`.

These +1-pp-above-threshold rows are reference operating points from the frozen effect grid, not replacements for the hard gates and not assumptions about the true confirmatory effects.

## Frozen evaluable-case rule

After the 512-case corpus is sealed:

1. no failed case may be replaced, replenished, or swapped based on outcomes;
2. arm-independent producer/deposition/pre-replay gates may mark a case non-evaluable before any arm outcome exists;
3. all such failures remain in the audit manifest with their pre-replay diagnostics;
4. if at least **496** cases remain evaluable, analysis proceeds on the sealed evaluable cohort, subject to the later-frozen stratum-completeness rule;
5. if fewer than **496** remain evaluable, the confirmatory execution is **inadmissible** and no campaign PASS/FAIL claim is issued.

The domain/case-type construction policy must still add stratum-level completeness constraints before corpus creation; the global 496 count alone does not protect against differential attrition concentrated in one stratum.

## What this establishes

The 512-case revision is statistically coherent under the now-explicit distinction between detection and hard-gate PASS:

- it preserves >80% conservative first-order detection power for +3 pp through paired SD 0.20 even at 496 evaluable cases;
- under the eligible instrumentation residual shape, +3-pp R−G detection is >90% at both 512 and 496;
- it does not falsely claim 80% campaign PASS at an effect exactly equal to its hard magnitude threshold;
- it provides high marginal hard-gate probabilities once true effects are modestly above the frozen thresholds;
- it avoids making an unsupported cross-contrast dependence assumption.

## Remaining pre-confirmatory blockers

Power/sample-size semantics are now sufficiently specified to proceed to the remaining freeze work, but **confirmatory case construction is still blocked** until the project freezes:

1. returned-model identity policy;
2. exact provider/prompt/generation/structured-output/retry/state policy;
3. domain/case-type strata and stratum-level evaluable-case requirements;
4. final scoring conventions and resource-boundary answer handling;
5. immutable manifest/seal procedure.

No confirmatory case may be created before those items are frozen.
