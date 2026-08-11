# Endogenous Demand Heterogeneity Audit

This analysis reconstructs the seven historical seed-level control/treatment pairs from Experiments 105, 109, and 110 so that the sign flip of aligned endogenous demand feedback can be examined without introducing new experimental conditions.

Predictors are measured only over the exact common prefix before the first cycle where the feedback treatment changes the generated task domain relative to the exogenous generator. The response is the seed-level change in logical early-incumbent share under the previously frozen aligned feedback strength λ=0.5.

The audit uses a fixed set of scalar state variables covering demand concentration, success concentration, allocation concentration, practice concentration, regime timing, and next-regime alignment. Candidate localization requires leave-one-out balanced accuracy of at least 0.75, leave-one-out accuracy of at least 5/7, stable threshold direction across leave-one-out fits, absolute Spearman correlation of at least 0.50, and a family-wise max-statistic permutation p-value no greater than 0.10 across the frozen feature set.

Any localized threshold remains hypothesis-generating because the seven historical seeds are used to discover it. Prospective validation on new seeds is required before calling it a phase-condition discovery. No Experiment 111+ is executed by this audit.
