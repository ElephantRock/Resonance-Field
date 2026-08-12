# Controlled Kick-Dose → Recovery-Time Campaign (Experiments 135–137)

This document operationalizes Issue #64. It is frozen before Experiment 135 execution.

## Purpose

Test prospectively whether increasing the number of externally imposed discrete award deviations prolongs macroscopic recovery, and whether untreated first-regime microscopic divergence is consistent with the proposed mediation chain.

The campaign does **not** test directed-percolation universality, a critical exponent, self-organized criticality, or a branching reproduction number.

## Frozen intervention

The nonzero dose is the count of controlled award deviations, `K ∈ {1,2,4}`. Every scheduled kick reuses the validated Auction Margin Control semantics: place the selected losing bid at radius `0.01` while preserving the natural winner, then apply the validated `ε=0.10` score-equivalent probe and require the awarded winner to change.

`K=0` is a matched counterfactual trajectory only. It defines pairwise divergence, recovery, and quality deltas; it is not entered on the `log2(K)` survival axis.

The environment is reputation-neutral, zero-turnover, aligned endogenous-demand feedback `λ=0.5`, 18-cycle regimes, seven candidates, activation at cycle 36, burst window 36–39, common landmark 54, and horizon 234.

## Timing balance and accepted asymmetry

Mean kick position is 37.5 at every nonzero dose. K=1 uses the four single-cycle positions equally in inferential cohorts; K=2 uses all six two-cycle combinations equally; K=4 necessarily uses `{36,37,38,39}` for every pair.

The resulting K=4 zero within-arm schedule variance is a preregistered accepted limitation. A qualitative K=4 departure cannot be separated by this campaign alone from that structural timing-dispersion asymmetry. It does not authorize post-hoc timing covariates, a wider burst, alternate K values, or phase stratification.

## Mediator and untreated-gap diagnostic

The confirmatory mediator window is cycles 54–71. Primary mediator: `early_micro_peak`; sensitivity mediator: `early_micro_auc`, both using the frozen microscopic pair-distance definition against K=0.

Cycles 40–53 are exported as a descriptive untreated-gap `D_micro`/component trace only. No gap statistic may enter a p-value, classifier, Cox model, mediation model, confirmatory endpoint, or rescue decision.

## Experiment 135

Instrumentation seeds and schedules are frozen in `configs/experiments/controlled-kick-dose-135-137.json`. The gate requires exact pre-activation identity, one preserved-then-crossed award deviation at every scheduled cycle, exactly K deviations, no experiment-local score adjustment after cycle 39, reputation neutrality, zero turnover, and all hard invariants.

Experiment 135 is instrumentation only. It cannot establish a dose-survival result.

## Experiments 136–137

If 135 validates, Experiment 136 is the 36-pair discovery cohort and Experiment 137 is a separate 36-pair same-environment replication cohort. The confirmatory survival trend is Cox PH with Breslow ties on `d=log2(K)` for K={1,2,4} only. All hazard ratios require 95% confidence intervals. RMST through 180 cycles must be nondecreasing with K. The mechanistic diagnostic additionally requires positive dose→`early_micro_peak`, negative conditional mediator→recovery hazard, and at least 20% attenuation of the dose coefficient in both discovery and replication.

No holdout, extra dose, alternate mediator window, alternate model family, or phase stratum may be added to rescue a null.
