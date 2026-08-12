# Experiment 136 — frozen discovery implementation note

This document records implementation semantics before any Experiment 136 outcome is observed. It does not amend the protocol in issue #64 or its pre-execution clarifications.

## Frozen allocation and timing

Discovery seeds are 2901–2936. Dose is assigned by the frozen modulo-3 rule: K=1, K=2, K=4, repeated in ascending seed order. Within each dose, schedules are assigned prospectively by within-dose ordinal from the frozen timing templates. K=1 uses `{36}`, `{37}`, `{38}`, `{39}` repeated three times; K=2 uses all six two-cycle combinations repeated twice; K=4 uses `{36,37,38,39}` for all 12 pairs. Mean kick position is 37.5 at every dose. The accepted K=4 zero-within-arm timing-variance limitation is unchanged.

The pre-136 natural-radius check logged on #64 remains descriptive only. `natural_radius` is exported as provenance but is not a dose weight, covariate, exclusion rule, stratum, mediator, or rescue variable.

## Frozen recovery computation

For every scientifically eligible kicked-vs-K=0 pair, the existing micro/meso/macro distance series is reconstructed through cycle 233. Persistent macro crossing uses the unchanged threshold 0.05 and 3-of-5 rule. Starting at landmark L=54, no persistent crossing gives `tau=1`. Otherwise terminal recovery is the first cycle after the final persistent five-cycle crossing window. A pair without terminal recovery by cycle 233 is right-censored at `tau=180`.

The full pair-distance series is retained in the workflow artifact so the endpoint can be reconstructed independently.

## Frozen survival implementation

The primary model is Cox PH with Breslow ties on the nonzero, scientifically eligible pairs only:

`tau ~ d`, where `d=log2(K)` and K is 1, 2, or 4.

The implementation does **not** standardize `d`; therefore the reported hazard ratio is per +1 unit of `d`, i.e. per doubling of K. Newton scoring uses the Breslow partial likelihood. A primary fit is numerically unstable if it does not converge, has singular/non-finite information, produces non-finite standard errors or confidence intervals, or exhibits coefficient divergence consistent with complete/quasi-complete separation. No alternate model is attempted after such a result.

The preregistered categorical shape model uses K=1 as reference with K=2 and K=4 indicators. Every reported Cox coefficient has a two-sided normal-Wald p-value and a 95% Wald hazard-ratio confidence interval.

Kaplan–Meier estimates are computed by dose. RMST is the area under the KM survival curve from 0 through the fixed 180-cycle horizon. No K=0 survival arm is fitted.

## Frozen mediation implementation

Link A fits ordinary least squares with an intercept, `early_micro_peak ~ d`, and reports the conventional two-sided Student-t slope test with `n-2` degrees of freedom. The primary mediator z-score uses the same population-SD standardization convention as audit #62.

Link B fits the Breslow Cox model `tau ~ d + early_micro_peak_z`. Attenuation is exactly `1 - abs(beta_d,Model2) / abs(beta_d,Model1)`. The same calculations are repeated for `early_micro_auc` as sensitivity only; the sensitivity mediator cannot rescue the primary mediation diagnostic.

Experiment 136 can only satisfy the discovery mediation conditions. The campaign-level `early_damage_mediation_consistent` label remains unavailable until Experiment 137 independently satisfies the same frozen conditions.

## Evidence and interpretation boundaries

Cycles 40–53 are retained/exported as the frozen untreated-gap diagnostic and are excluded from p-values, Cox models, OLS models, mediators, dose construction, and gating. All kick audits, full pair-distance series, mediator-window rows, Kaplan–Meier steps, pair summaries, quality deltas, basin agreement, and winner-synchronization summaries are retained in the Experiment 136 artifact.

A successful Experiment 136 gate is discovery only. No robust causal dose-survival conclusion is available without independent Experiment 137 replication. Production behavior remains unchanged and reputation-neutral.
