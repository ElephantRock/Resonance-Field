# Adaptive Integration Campaign — Experiments 014–040

This campaign moves the validated Experiment 013 reputation policy into the real PostgreSQL task market and conducts twenty-seven consecutive experiments. Experiment 014 is fixed by the prior result. Every later experiment is selected from the immediately preceding measured failure.

## Starting policy

Experiment 013 validated:

```text
blend-w0.55-fresh24-g2-p2-n1-r0.8-b0.25
```

Interpretation:

- reputation influence 0.55;
- 24-cycle active freshness half-life;
- evidence-mass gate 2;
- positive evidence weight 2;
- negative evidence weight 1;
- 80% regime reset of pre-shift evidence influence;
- 75% task-domain / 25% required-skill blend.

Historical evidence remains persistent and auditable. Only its active auction influence is freshness- and context-sensitive.

## Experiment 014

Fixed question:

> Can the Experiment 013 policy preserve its advantage inside the real PostgreSQL sealed-bid market with escrow, settlement, persistent evidence, and immutable score provenance?

Experiment 014 compares:

1. production-default no reputation;
2. raw persistent domain reputation;
3. the Experiment 013 validated policy.

All tasks use `PostgresMarketService`, real sealed bids, compute-credit escrow, double-entry settlement, persistent Beta evidence, verified substrate traces, and the system-owned auction-signal interface.

## System-owned auction signals

The production default remains neutral. Bids contain only bidder-owned fields such as price, confidence, estimated completion time, and strategy summary. A controller-owned `BidSignalProvider` may add an adjustment at award time.

For every eligible bid, the market persists an immutable score record containing:

- baseline bid score;
- system signal adjustment;
- total score;
- provider label;
- structured signal components;
- selected/not-selected outcome;
- capture timestamp.

Agents cannot submit these fields through their bids.

## Hard invariants

A candidate arm cannot advance unless all of the following hold:

- total compute credits remain conserved;
- every compute transaction remains balanced;
- completed task escrow is zero;
- every eligible bid has immutable score provenance;
- exactly one score row is selected per awarded task;
- sealed bids reject economic/content mutation;
- score provenance rejects update/delete mutation;
- duplicate reputation evidence remains idempotent;
- no reputation operation transfers Compute Credits.

These constraints dominate all emergence metrics.

## Adaptive local-search phase — Experiments 015–037

There are twenty-three possible intervention dimensions. Their experiment-number order is **not fixed**. The preceding result is classified as quality, plasticity, concentration, calibration, economic distortion, integrity, weak structure, or robustness. That failure chooses the highest-priority untested dimension.

The intervention catalog is:

```text
reputation_weight
freshness
blend_skill
mass_gate
positive_weight
negative_weight
shift_reset
temperature
score_cap
uncertainty_prior
exposure_penalty
exposure_window
candidate_count
task_budget
trace_half_life
confidence_evidence
confidence_noise
practice_gain
shift_period
price_pressure
speed_pressure
evidence_noise
requester_skew
```

Each experiment runs a neutral control, the incumbent, and two local alternatives. A null result is valid evidence: the incumbent stays and the next failure-selected dimension is tested.

## Metrics

Each arm reports paired-seed means for:

- task success rate;
- agent/domain mutual information;
- mean specialization;
- winner HHI;
- early post-shift incumbent share;
- winner replacement rate;
- reputation Brier score;
- mean winning-price / task-budget ratio;
- final Compute Credit Gini coefficient;
- every hard invariant above.

Selection requires quality, plasticity, and economic metrics to stay within configured tolerances of the no-reputation control. Among feasible reputation arms, constrained utility rewards task success and useful structure while penalizing incumbency, miscalibration, price inflation, and credit concentration.

## Experiment 038 — adaptive stress

Experiment 037 selects the stressor from its remaining failure. Possible stressors include thin markets, rapid regime shifts, evidence corruption, credit scarcity, trace-memory collapse, integrity replay pressure, or a mixed shock.

The stressed experiment compares the incumbent against two failure-specific rescue policies plus a neutral control.

## Experiment 039 — adaptive replication/adversarial scenario

Experiment 038 selects the replication scenario. Possible scenarios include confidence inflation, incumbent pressure, label noise, price shading, replay pressure, or a mixed replication environment.

The result chooses the holdout shock.

## Experiment 040 — unseen-seed holdout

Experiment 040 uses unseen seeds and the shock selected by Experiment 039. It compares:

- no reputation;
- raw persistent reputation;
- the final policy selected by Experiments 014–039.

Validation requires every hard invariant, feasibility relative to control, no material success deficit, and constrained utility no more than 0.005 below the neutral control.

## Evidence

The post-merge workflow exports:

- `campaign.json`;
- `experiment-014.json` through `experiment-040.json`;
- `experiment-arms.csv`;
- `runs.csv`;
- `outcomes.csv`;
- `auction_scores.csv`;
- `reputation_evidence.csv`;
- `compute_transactions.csv`.

Each experiment publishes its motivating failure, observed failure, selected arm, metrics, invariant detail, and next focus to issue #15.

## Interpretation boundary

Passing Experiment 040 would establish the selected scorer as an integration-validated candidate. It would not automatically enable reputation in production. The production constructor remains reputation-neutral unless a controller explicitly supplies a system-owned signal provider.
