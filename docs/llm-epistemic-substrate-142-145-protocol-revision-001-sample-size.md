# Protocol Revision 001 — Confirmatory Sample Size

Date: 2026-08-12
Campaign: `llm-epistemic-substrate-142-145-v0.1`
Status: pre-confirmatory, before corpus creation or seal

## Revision

Increase the planned confirmatory cohort from **96 to 512 independent cases** while preserving:

- primary endpoint: `post_agent_task_accuracy`;
- five evaluator draws per case/arm;
- four planned paired contrasts and Holm family-wise alpha 0.05;
- provisional minimum R−G effect: **+0.03 absolute**;
- provisional minimum R−P effect: **+0.08 absolute**;
- P/S/G/R treatment definitions;
- 12-unit per-call, 24-unit per-answer, and 8-round evaluator ceilings.

No confirmatory case has been created, opened, or evaluated before this revision.

## Reason

The original 96-case scaffold and the 3-pp R−G target were not shown to be statistically compatible when cases are correctly treated as the independent units.

The pre-confirmatory design-adequacy audit estimated case-level R−G paired SD at approximately `0.1789` using only instrumentation cases without a known frozen-primary scoring defect. That variance estimate is used for planning only; the observed mean treatment effect is not used as the target alternative.

Under a conservative first Holm step across four contrasts (`alpha = 0.0125`, two-sided) and 80% nominal power, the normal paired-mean approximation requires approximately:

- 397 cases at paired SD `0.1789` for a 3-pp effect;
- 496 cases at paired SD `0.20` for a 3-pp effect.

The revised count of **512** provides a modest planning margin through paired SD approximately `0.20`, while preserving the scientific 3-pp R−G sensitivity target rather than weakening that target to fit the original budget.

Detailed adequacy record: `docs/llm-epistemic-substrate-142-145-confirmatory-design-adequacy.md`.

## Why this is not outcome tuning

This revision responds to **variance and design precision**, not to whether instrumentation favored R, G, P, or S.

The instrumentation outcome-tuning stop remains in force. In particular:

- the primary endpoint is unchanged;
- treatment definitions are unchanged;
- resource ceilings are unchanged;
- the 3-pp R−G target is preserved rather than moved toward observed case effects;
- no secondary endpoint is promoted;
- no confirmatory information exists to condition the decision on.

## Independent-unit rule

The 512 count means **512 research cases**, not evaluator draws.

Each case still contains five stochastic evaluator draws per arm. Those draws are nested repeated measurements and are first reduced to a case/arm mean for the paired confirmatory analysis. Bootstrap and randomization operate on cases.

The resulting planned execution scale is:

- 512 independent cases;
- four arms per case;
- five evaluator draws per arm;
- 10,240 evaluator case-arm draws total if every arm-independent pre-replay gate passes;
- producer execution still occurs exactly once per case before replay into all arms.

## Case-strata consequence

The larger cohort permits balanced confirmatory construction. The exact domain/case-type strata remain to be frozen before case creation. A natural 512-case design can use powers-of-two or equal stratum sizes without fractional allocation, but this revision does **not** create or inspect any case content.

## Remaining power requirement

The normal approximation is a design screen, not the final power proof. Before confirmatory sealing, the repository must add and freeze a deterministic simulation/precision analysis tied to the final case-level paired estimator. The simulation must verify the 512-case design under the final multiplicity and missing/evaluable-case rules.

If that prospective simulation shows that 512 cases are still inadequate under the frozen planning assumptions, the protocol must fail the pre-seal adequacy gate; the project may not compensate after confirmatory content is created.

## Confirmatory boundary

At this revision:

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- confirmatory cases sealed: false
- confirmatory cases created: false

This revision changes planned sample size only. It does not authorize confirmatory corpus construction or execution.
