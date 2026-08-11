# Censored Cascade-Survival Audit

Issue #62 is a read-only reanalysis of the completed Experiments 129–134 evidence.

It uses only the retained outputs from the completed Post-Crossing Reconvergence Audit (#60). It does not run Experiment 135, create new treatment cells, or alter any production or experimental mechanism.

## Frozen primary analysis

The primary population is the 25 basin-agreeing pairs that experienced a persistent macro crossing. Macro recovery uses the already-frozen `macro_terminal_recovery` rule; recoveries beyond the observed horizon are right-censored.

The two co-primary predictors use only the first complete post-activation regime:

- `early_micro_peak`
- `early_micro_auc`

Each is standardized with the population standard deviation of the frozen primary sample and fitted separately in a univariate Cox proportional-hazards model with Breslow tie handling.

`survival_signal_supported` requires both hazard ratios below 1, both two-sided Wald p-values at or below 0.10, at least one raw p-value at or below 0.025, the same directions in the all-28 macro-crossed robustness population, and exact reproduction of the #60 historical class counts/invariants.

A supported result is limited to a censored cascade-survival association. It is not evidence for a directed-percolation universality class, a critical exponent, or a causal branching reproduction number.

## Winner-disagreement proxy

`T_sync` is the first post-activation start of a same-winner run lasting one complete environment regime. The run length is therefore 18 cycles in the standard/timing environments and 15 in the holdout environment. No run-length search is permitted.

The proxy is reported as directional evidence only and cannot be called `R_D`.

## Downstream decision

If the primary survival gate is supported, the next scientific step is a separately preregistered minimal controlled-kick-size versus recovery-time experiment, not the full Branch-Cascade 135–140 family.

If it is not supported, the next permissible work is discrete causal-event instrumentation before any separately preregistered channel-interruption family.

No Experiment 135+ is authorized by this audit.
