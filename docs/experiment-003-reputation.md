# Experiment 003 — Reputation Plasticity

## Research question

> Can persistent, evidence-backed reputation improve delegation quality and stabilize useful specialization under active trace decay without creating permanent incumbents when the environment changes?

This experiment follows Experiment 002, which demonstrated that finite trace decay produces retrieval turnover and resurrection. Experiment 003 keeps forgetting active and introduces a separate persistent reputation signal.

## Scientific boundary

All agents begin with the same capabilities, the same neutral Beta prior, the same credit allocation, and no role labels. There are no predefined experts. Differentiation can arise only from task exposure, successful work, accumulated practice, decaying verified evidence, and persistent reputation evidence.

Reputation is non-spendable. It cannot transfer compute credits, alter policy, modify safety controls, or directly rewrite traces.

## Factorial arms

| Arm | Verified-trace half-life | Reputation used in auction |
|---|---:|---|
| `slow_reputation` | 900 s | yes |
| `slow_no_reputation` | 900 s | no |
| `fast_reputation` | 120 s | yes |
| `fast_no_reputation` | 120 s | no |

Five seeds are run for every arm: 101, 202, 303, 404, and 505. This produces 20 independent PostgreSQL + pgvector cells.

## Delegation loop

Every cycle creates one environmental delegation task in one of six domains. The requester rotates through the population. A deterministic subset of eight non-requester agents is eligible to bid.

Candidate membership and the random-looking bid components are functions only of seed, cycle, and agent slot. They therefore remain paired across experimental arms.

For each candidate:

1. the environment reads the current energy of that agent's most energetic verified-success trace for the skill required by the task;
2. that ephemeral evidence signal contributes to bid confidence;
3. ordinary market bid score is calculated from confidence, price efficiency, and estimated speed;
4. persistent domain reputation is optionally added as an adjustment around the neutral 0.5 prior.

The reputation-enabled total score is:

\[
Score = BidScore + w_r(R - 0.5)
\]

where `R` is the contextual Beta posterior mean and `w_r = 0.45` in v0.1.

The no-reputation arms use the exact same baseline bid score but set the reputation adjustment to zero. Reputation evidence is still recorded in those arms so calibration can be measured counterfactually without influencing selection.

## Reputation evidence

For every completed task, the winner receives one auditable evidence update in the task domain:

\[
R = \frac{\alpha}{\alpha+\beta}
\]

A success increments `alpha`; a failure increments `beta`. Priors are `Beta(1,1)`. Evidence does not decay during the experiment.

Every update stores:

- agent;
- dimension;
- context key;
- positive/negative outcome;
- evidence weight;
- alpha/beta before and after;
- source type and source task ID;
- timestamp.

Duplicate source evidence is idempotent.

## Verified skill evidence and forgetting

Successful delegated work also writes a `VERIFIED_OUTCOME` trace into the substrate. The trace is labeled by the skill actually required by the task, authored by the winner, and given the arm's configured half-life.

This creates the intended separation:

- reputation remembers persistent outcome history for a task domain;
- substrate evidence remembers recent verified skill activity and fades with time.

## Learning by doing

Agents have no initial skill differences. Dynamic competence comes from accumulated practice in a skill basin.

For the awarded agent, success probability is:

\[
P(success)=\min(P_{max}, P_0 + g\sqrt{practice})
\]

with `P0 = 0.38`, `g = 0.10`, and `Pmax = 0.90`.

Practice increases only through actually receiving delegated work. This creates path-dependent competence without assigning professions.

## Regime shift

Cycles 0–89 use the identity mapping:

```text
urban_heat      -> urban_heat
water_systems   -> water_systems
...
```

At cycle 90, every task domain rotates to require the adjacent skill basin:

```text
urban_heat      -> water_systems
water_systems   -> energy_storage
energy_storage  -> supply_networks
supply_networks -> public_health
public_health   -> mobility
mobility        -> urban_heat
```

The task-domain reputation label does not rotate. This intentionally makes old reputation partially stale.

The newly relevant specialists are instead indicated by their decaying verified skill traces and practice history. A useful reputation mechanism should provide pre-shift assignment value but eventually yield to new outcome evidence rather than permanently protecting old incumbents.

## Primary metrics

### Delegation quality

- overall success rate;
- pre-shift success rate;
- early post-shift success rate;
- late post-shift success rate.

### Structural differentiation

- mutual information between winner identity and task domain;
- mean winner domain specialization;
- mean within-domain winner HHI;
- number of unique winners.

### Reputation quality

- Brier score of the selected winner's pre-outcome reputation probability against the observed binary outcome;
- total persistent reputation evidence records.

### Incumbency and plasticity

For each domain, the pre-shift incumbent is the agent with the most awards before cycle 90.

We then measure:

- share of early post-shift awards retained by those incumbents;
- share of late post-shift awards retained by those incumbents;
- decline in incumbent share;
- fraction of domains whose dominant post-shift winner differs from the pre-shift incumbent;
- adaptation latency: first trailing post-shift window in which old incumbents receive at most half of awards.

## Interpretive outcomes

A useful reputation mechanism should show some combination of:

- higher pre-shift success than the paired no-reputation arm;
- stronger but not total domain specialization;
- better calibration as evidence accumulates;
- an early post-shift cost from stale reputation that later recovers;
- declining incumbent share rather than permanent lock-in;
- comparable or improved late post-shift success.

A failure mode would be reputation improving early exploitation but preserving old incumbents after their task-domain signal becomes stale, especially if late post-shift success remains below the no-reputation control.

## Reproducibility

Run identity is derived from:

```text
code SHA + config hash + arm + seed
```

Each matrix cell exports:

- `experiment.json`;
- `outcomes.csv`;
- `auction_scores.csv`;
- `reputation.csv`;
- `reputation_evidence.csv`;
- `tasks.csv`;
- `traces.csv`;
- `postgres.sql`.

Compact cell summaries are posted to Experiment 003 issue #11.
