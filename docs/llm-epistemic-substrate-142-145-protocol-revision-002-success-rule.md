# Protocol Revision 002 — Campaign Success and Power Semantics

Date: 2026-08-12
Campaign: `llm-epistemic-substrate-142-145-v0.1`
Status: pre-confirmatory, before corpus creation or seal

## Purpose

Freeze the confirmatory PASS rule and remove an ambiguity between a **hard minimum observed-effect gate** and a **power-analysis alternative**.

No confirmatory case has been created, opened, sealed, or evaluated before this revision.

## Parent-campaign precedent

Experiments 138–141 did not use their preregistered `+0.10` minimum effects merely as descriptive planning values. The frozen confirmatory analyzer defined campaign success by requiring each gated total R−P primary endpoint to satisfy all three conditions simultaneously:

1. observed paired effect at least `+0.10`;
2. Holm-adjusted p-value below `0.05`;
3. paired-bootstrap 95% CI lower bound above `0`.

The parent results document and tests explicitly enforced that hard-gate semantics.

Experiments 142–145 preserve that logic while adapting it to one primary endpoint and two priority causal contrasts.

## Frozen 142–145 campaign PASS rule

The four preregistered paired contrasts remain in one Holm family:

1. S − P;
2. G − S;
3. R − G;
4. R − P.

S−P and G−S are estimated and multiplicity-adjusted but do not gate campaign PASS.

The two priority contrasts are hard gates:

### Incremental field gate: R − G

PASS requires all of:

- observed case-level mean accuracy effect `>= +0.03`;
- Holm-adjusted two-sided paired-randomization p-value `< 0.05`;
- paired-bootstrap 95% lower bound `> 0`.

### Total substrate gate: R − P

PASS requires all of:

- observed case-level mean accuracy effect `>= +0.08`;
- Holm-adjusted two-sided paired-randomization p-value `< 0.05`;
- paired-bootstrap 95% lower bound `> 0`.

### Campaign PASS

`campaign_success = true` only when **both** priority gates pass.

A significant R−G effect below +3 pp is therefore scientifically interesting but is not a campaign PASS. Likewise, a point estimate above +3 pp without multiplicity-adjusted statistical support or with a non-positive lower confidence bound is not a campaign PASS.

Implementation: `src/resonance/experiments/llm_epistemic_confirmatory_analysis.py`.

## Why the power semantics must be separated

A hard observed-effect threshold and a hypothesis-test alternative are different quantities.

Suppose the true R−G effect is exactly the hard threshold, `delta = +0.03`. Even with an arbitrarily precise unbiased estimator, sampling variation is approximately symmetric around +0.03. The probability that the observed point estimate is at least +0.03 therefore approaches roughly 50%, not 80%.

Consequently, no finite sample size can honestly be described as giving 80% **campaign-PASS probability at a true effect exactly equal to the hard threshold** when PASS itself requires the point estimate to be at least that threshold.

This does not make the hard gate incoherent. It means power must be reported using two different quantities.

## Frozen power reporting semantics

### 1. Detection power

`detection_power(delta)` is the probability that a priority contrast is statistically positive against the zero-effect null under the frozen multiplicity rule:

- Holm rejection in the four-contrast family; and
- paired-bootstrap lower bound above zero.

The original Protocol Revision 001 planning calculation for the 512-case design is a **detection-power calculation**. Its statement that roughly 397 cases are required at paired SD `0.1789` and 496 cases at paired SD `0.20` for a +3-pp effect refers to approximately 80% detection power against zero under the conservative first Holm threshold.

It does **not** mean 80% campaign-PASS probability at exactly +3 pp.

### 2. Hard-gate / joint PASS probability

`gate_pass_probability(delta)` additionally requires the observed effect to meet the frozen magnitude gate.

For R−G, this means effect `>= +0.03` plus statistical positivity. For R−P, effect `>= +0.08` plus statistical positivity.

The pre-seal power analysis must report this probability over a prospectively fixed effect grid that includes:

- the null (`0`);
- the exact hard threshold;
- values immediately above the threshold; and
- larger scientifically plausible values.

The threshold row is expected to have joint PASS probability near 50% when the magnitude gate is the binding condition. That is a property of the rule, not a reason to move the gate after outcomes.

## Sample-size implication

Protocol Revision 001 remains in force:

- 512 independent confirmatory cases;
- five nested evaluator draws per case/arm;
- R−G minimum observed-effect gate +3 pp;
- R−P minimum observed-effect gate +8 pp;
- four-contrast Holm family at alpha 0.05.

The justification for 512 is now stated precisely: it provides conservative first-order **detection power** for a nonzero +3-pp R−G effect through planning paired SD approximately 0.20.

The final deterministic pre-seal simulation must separately quantify joint hard-gate PASS probabilities. It may block sealing if the design behaves unacceptably under the frozen planning assumptions, but it may not change the gate or sample size after confirmatory case content exists.

## Interpretation states

The final report will distinguish at least:

- **Campaign PASS:** both R−G and R−P hard gates pass;
- **positive but sub-threshold:** statistically positive priority effect but observed magnitude below its hard gate;
- **magnitude without statistical support:** observed magnitude clears the gate but Holm/CI requirement fails;
- **no positive confirmatory effect:** statistical positivity fails;
- **inadmissible execution:** confirmatory quality/seal/model/evaluable-case gates fail, so no scientific PASS/FAIL inference is issued.

These states prevent a binary label from hiding why a campaign did or did not satisfy its preregistered claim.

## Anti-tuning constraint

This revision does not change any observed-effect threshold, arm definition, primary endpoint, multiplicity family, resource limit, or confirmatory case count. It clarifies the semantics required to make the already-selected design auditable.

No instrumentation outcome after Calibration 008 may be used to alter this rule.

## Confirmatory boundary

At this revision:

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- planned confirmatory cases: `512`
- confirmatory cases created: false
- confirmatory cases sealed: false

The next statistical task is a deterministic pre-seal power simulation that reports both detection power and hard-gate PASS probability under the frozen 512-case rule.
