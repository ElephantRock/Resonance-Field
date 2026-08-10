# Two-Timescale Campaign — Experiments 053–062

## Research question

Experiments 041–052 rejected a universal one-dimensional rule based only on `tau_R / tau_L`. The next hypothesis separates two organizational clocks:

- `tau_F`: capability-backed specialization formation time.
- `tau_D`: obsolete-specialization decay time after a clean skill remap.
- `tau_R`: environmental regime duration.

The candidate explanatory rule is two-dimensional:

`reputation usefulness = f(tau_R / tau_F, tau_R / tau_D)`

## Measurements

### Formation time (`tau_F`)

A stable task-to-skill mapping is run with the real sealed-bid market. From persisted winner/required-skill observations, the campaign reconstructs each selected agent's practiced-skill count before every outcome and therefore the experiment's configured expected success probability. `tau_F` is the first persistent rolling window whose mean expected competence reaches a fixed fraction of the configured base-to-maximum capability range.

This deliberately replaces the prior MI-crossing clock, which did not move when practice gain changed.

### Forgetting time (`tau_D`)

A two-regime experiment establishes pre-shift task-domain incumbents from the final pre-shift reference window. After the skill remap, the campaign measures the rolling share of tasks still awarded to those old incumbents. `tau_D` is the first persistent window in which that share has fallen halfway from its measured pre-shift value toward the candidate-set chance floor.

The no-reputation control receives the same measurement so reputation-specific retention can be distinguished from ordinary market persistence.

## Sequence

1. 053 — baseline formation.
2. 054 — baseline forgetting.
3. 055 — slow-practice formation.
4. 056 — slow-practice forgetting.
5. 057 — fast-practice formation.
6. 058 — fast-practice forgetting.
7. 059 — fit a deterministic two-threshold rule and test it on an interpolated, previously unseen practice gain.
8. 060 — derive one reputation-weight gate from the measured rule; no coefficient sweep.
9. 061 — independent-seed replication.
10. 062 — unseen-seed holdout at a second unseen practice gain on the opposite side of the inferred boundary.

## Model

For each measured condition:

- `r_F = tau_R / tau_F`
- `r_D = tau_R / tau_D`

A deterministic grid over observed ratios selects `theta_F` and `theta_D` that best classify whether reference reputation is positive and feasible. The predicted state depends on the limiting normalized ratio:

`score = min(r_F / theta_F, r_D / theta_D)`

A neutral band is retained around 1.0 so small effects are not forced into a sign.

## Derived mechanism

Experiment 060 tests only one mechanism:

`reputation_weight_active = reputation_weight_reference * clamp(score, 0, 1)`

The immutable reputation evidence ledger is unchanged. Only the active market influence is reduced when either formation or forgetting is too slow for the current regime.

## Hard gates

Every cell still requires:

- conserved and balanced Compute Credits;
- zero completed-task escrow;
- complete and immutable auction-score provenance;
- immutable sealed bids;
- idempotent reputation evidence; and
- non-spendable reputation.

Production remains reputation-neutral regardless of campaign outcome. A successful campaign requires Experiment 062 to validate both the two-timescale sign prediction and the candidate mechanism on unseen seeds without violating the existing quality/plasticity/economic gates.
