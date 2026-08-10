# Phase Boundary Campaign — Experiments 041–052

Experiments 014–040 validated the real PostgreSQL integration machinery but rejected the final adaptive reputation policy on an unseen rapid-regime-shift holdout. The strongest surviving hypothesis is a timescale interaction rather than a universal reputation coefficient.

## Research question

Let:

- `tau_L` be the empirical time required for identity-conditioned specialization to reach half of its stable-regime mutual-information level;
- `tau_R` be the duration of an environmental regime before the task-domain to required-skill mapping changes.

The campaign asks whether there is a crossover ratio `theta` such that reputation tends to help when `tau_R / tau_L > theta` and tends to hurt when `tau_R / tau_L < theta`.

This is a phase-boundary experiment, not a parameter sweep.

## Fixed reputation mechanism

The primary comparison uses the pre-stress policy that emerged before Experiment 038:

- system-owned reputation signal;
- weight `0.45`;
- persistent evidence influence;
- `25%` required-skill / `75%` task-domain context blend;
- regime reset `0.10`;
- score cap `0.20`;
- exposure penalty `0.04` over a 12-cycle window.

Production remains reputation-neutral. This policy exists only inside the experiment provider.

## Sequence

### Experiment 041 — learning timescale

Run an effectively stable regime and measure the first sustained cycle at which cumulative agent/domain mutual information reaches 50% of its final stable-regime level. The paired neutral and reference-reputation arms use identical deterministic tasks, candidate sets, prices, confidence noise, and outcomes.

### Experiments 042–045 — adaptive bracketing

Start at `tau_R ≈ tau_L`. After each result:

- if reputation is beneficial, shorten the next regime;
- if reputation is harmful or infeasible, lengthen the next regime;
- once positive and negative observations bracket a crossover, bisect the tightest bracket.

The sign is based on task-success delta versus the neutral control, with feasibility constraints still active.

### Experiments 046–049 — scaling test

Change practice gain to alter `tau_L`, remeasure the learning timescale, and test the regime duration predicted by the current boundary ratio. The observed sign updates `theta` before the next learning-rate condition.

A true timescale law should move with `tau_L`; a fixed-cycle rule should not.

### Experiment 050 — mechanism test

Test a simple timescale gate just below the inferred boundary. The reputation weight is multiplied by:

`clamp((tau_R / tau_L) / theta, 0, 1)`

This preserves the immutable evidence ledger while reducing only active allocation influence when the environment is changing faster than specialization can form.

### Experiment 051 — independent replication

Replicate the candidate policy on an independent seed set near the inferred boundary.

### Experiment 052 — unseen holdout

On unseen seeds, compare:

1. no reputation;
2. the fixed reference reputation policy;
3. the candidate timescale policy.

Validation requires the inferred boundary to predict the sign of the reference policy's success effect, the candidate to remain feasible, and all hard integration invariants to hold.

## Hard invariants

Every cell continues through the real PostgreSQL market and must preserve:

- conserved Compute Credits;
- balanced double-entry postings;
- zero balance in completed task escrow;
- complete auction-score provenance for every eligible bid;
- exactly one selected score row per awarded task;
- immutable sealed bids;
- immutable score provenance;
- idempotent reputation evidence;
- non-spendable reputation.

## Evidence

The workflow exports the campaign summary, per-experiment JSON, arm metrics, runs, outcomes, auction scores, reputation evidence, and compute transactions. Issue #17 is the durable lab notebook.

A failed boundary or holdout is a valid result. No campaign result changes the production market's reputation-neutral default automatically.
