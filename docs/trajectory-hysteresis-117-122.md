# Trajectory/Hysteresis — Experiments 117–122

Canonical preregistration: GitHub issue #46.

This campaign tests whether the sign of the frozen aligned endogenous-demand controller (λ=0.5) depends on **how the organization arrived at its pre-activation state**. It deliberately compares histories whose five previously frozen instantaneous state observables are tolerance-matched rather than exactly equal.

Four prefix histories are frozen: smooth exogenous reference, weak aligned feedback, weak permuted-source feedback, and a small exogenous annealing/noise history. All history interventions are disabled for a one-regime washout before activation. Every history has its own post-activation λ=0 counterfactual and λ=0.5 treatment, so the measured effect is conditional on that exact history.

Primary hysteresis evidence requires matched endpoints, materially different trajectories, a ≥2pp mean absolute feedback-effect gap, ≥40% sign discordance, independent replication, a mid-regime timing control, and an unseen shift-period holdout. Endpoint matching uses only pre-activation features with fixed tolerances (≤0.10 per feature and ≤0.06 RMS distance).

Trajectory observables are frozen to path length, ternary-basin transitions, terminal momentum, and trajectory roughness. At most one scalar predictor may be selected in Experiment 119 from the 12 smooth-reference discovery records with exhaustive family-wise permutation correction; it may never be refit later.

The annealed history is a separate preregistered glassy-consistency test: if small independent prefix perturbations make feedback sign more concentrated and lower sign entropy across all validation cohorts, the next campaign should systematically study noise magnitude and correlation structure. If the matched-endpoint hysteresis chain fails, the next preregistered hypothesis is chaos / rapid predictability decay rather than further tolerance or threshold searches.

Production behavior remains unchanged and reputation-neutral. External-boundary issue #42 remains blocked throughout this campaign.
