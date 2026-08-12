# Experiment 137 — frozen independent replication implementation note

This document records implementation semantics for the preregistered Experiment 137 replication in issue #64. It does not amend the protocol or reinterpret Experiment 136.

## Frozen cohort and timing

Replication seeds are 3001–3036. Dose is assigned by the unchanged modulo-3 sequence K=1, K=2, K=4 in ascending seed order. Within each dose, the same prospectively frozen timing templates used for Experiment 136 are assigned by within-dose ordinal. K=1 uses `{36}`, `{37}`, `{38}`, `{39}` repeated three times; K=2 uses all six two-cycle combinations repeated twice; K=4 uses `{36,37,38,39}` for all 12 pairs. Mean kick position remains 37.5 at every dose.

No seed is replaced. Every scheduled kick must preserve the natural winner before the probe and cross to the predicted awarded winner after the probe. Production behavior outside the experiment-local wrapper remains unchanged.

## Independence boundary

The Experiment 137 workflow downloads only the validated Experiment 135 instrumentation artifact needed to verify the frozen controller/config dependency. It does **not** download, read, fit to, gate on, or otherwise use the Experiment 136 artifact or outcomes.

Experiment 136 remains a separately frozen discovery result. Experiment 137 can satisfy only its own preregistered replication gate. Campaign-level interpretation is performed only after the replication artifact is frozen and independently verified.

## Frozen endpoint and analyses

Recovery is unchanged from Experiment 136: macro threshold 0.05, persistent 3-of-5 crossing, common landmark L=54, terminal recovery, and right-censoring at tau=180. The primary population contains only scientifically eligible K in {1,2,4} pairs; K=0 is the matched counterfactual trajectory and is not a survival subject.

The primary model is Cox PH with Breslow ties, `tau ~ log2(K)`. Replication validates only if the coefficient is negative, the two-sided Wald p-value is <=0.05, RMST(180) is nondecreasing across K=1,2,4, and the frozen quality and invariant gates pass. The categorical K=1-reference Cox model remains shape characterization only.

The primary mechanistic replication diagnostic remains `early_micro_peak`: dose-to-mediator OLS must be positive and significant, the conditional mediator Cox coefficient must be negative and significant, and dose attenuation must be at least 20%. `early_micro_auc` remains sensitivity only and cannot rescue failure of the primary mediator.

## Retained evidence

The artifact retains pair summaries, full pair-distance series, untreated cycles 40–53, mediator cycles 54–71, Kaplan–Meier steps, kick audits including natural radii, quality deltas, basin agreement, and winner synchronization. Gap traces and natural-radius values remain descriptive only and cannot enter confirmatory models, exclusions, weighting, mediation, or rescue analyses.
