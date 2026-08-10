# Experiment 002 — Decay Stress

Experiment 001 showed no difference between `full` and `no_decay`. Experiment 002 is a targeted falsification attempt: it changes the environment and instrumentation so trace decay has a direct opportunity to alter retrieval.

## Research question

> Does trace decay create measurable ecological turnover in retrieval, or is decay currently architectural decoration?

This is a substrate/ecology experiment, not an LLM-emergence claim. All agents use the same deterministic general-purpose policy.

## Arms

| Arm | Half-life |
|---|---:|
| `fast_decay` | 120 s |
| `slow_decay` | 900 s |
| `no_decay` | 1e12 s |

The three arms receive identical agents, seeds, initial traces, semantic neighborhoods, novel-trace injections, action costs, and probe schedule. The only intended causal difference is trace half-life.

## Population and horizon

- 20 initially equivalent agents
- 120 cycles
- 30 seconds of simulated time per cycle
- seeds: 101, 202, 303, 404, 505
- 15 matrix cells total
- equal initial compute credits

## Semantic neighborhoods

Six local basins are used:

- urban heat
- water systems
- energy storage
- supply networks
- public health
- mobility

Each neighborhood starts with five highly similar competing traces. Their absolute ages are staggered by 0, 1, 2, 4, and 8 fast-decay half-lives. Older traces begin with higher energy and higher evidence quality, creating a deliberate conflict between accumulated quality and freshness.

Embeddings share a neighborhood axis plus a small deterministic perturbation. Competing traces therefore remain semantically close enough that energy decay can influence ordering. Cross-neighborhood traces remain much less similar.

## Controlled environmental perturbation

Every six cycles, the environment injects one new deterministic trace into every neighborhood. Injection IDs, embeddings, quality, and initial energy are functions of seed, cycle, and neighborhood and are therefore identical across arms.

Novel-trace injection is environmental rather than an agent profession or role. It supplies controlled ecological pressure while isolating decay.

## Agent policy

Every agent follows the same rule:

1. query one deterministically selected semantic neighborhood;
2. if a retrieved non-top trace is below the cooling threshold and the seeded policy draw permits it, reinforce that trace;
3. otherwise perform a substrate query only.

The policy does not know which experimental arm it is in. Different behavior can arise only because the retrieved state differs.

## Retrieval probes

Every cycle, each neighborhood is probed twice:

- `pre`: after any scheduled novel-trace injection and before agent actions;
- `post`: after all agent actions for the cycle.

For every rank, the system persists:

- trace ID;
- retrieval score;
- current energy;
- semantic similarity;
- trace age;
- cycle, phase, neighborhood, and timestamp.

This makes decay effects observable directly rather than inferred from endpoint summaries.

## Resurrection criterion

A reinforcement attempt is recorded when an agent selects a cooling non-top trace. A resurrection is confirmed only when all are true:

1. pre-reinforcement energy is at or below the configured cooling threshold;
2. the trace was not rank 1;
3. reinforcement improves its rank;
4. it returns to the top two immediately after reinforcement.

This is intentionally stricter than counting reinforcement alone.

## Primary metrics

### Top-trace turnover

Fraction of consecutive post-cycle probes in which the rank-1 trace changes.

### Top-k Jaccard turnover

For consecutive post-cycle retrieval sets:

\[
T_J = 1 - \frac{|A \cap B|}{|A \cup B|}
\]

### Mean rank displacement

Mean absolute rank movement among traces present in both consecutive retrieval sets.

### Same-cycle top change

Fraction of cycle/neighborhood pairs where the pre-action and post-action rank-1 traces differ. This isolates immediate downstream effects of agent interventions.

### Evidence age

- mean age of rank-1 traces;
- mean age of all retrieved traces;
- share of retrieved traces older than two fast-decay half-lives.

### Top-trace diversity

- unique traces that occupy rank 1;
- entropy of rank-1 identity over the run.

### Resurrection

- reinforcement attempts against cooling traces;
- confirmed resurrections;
- confirmation rate.

## Interpretation

Evidence that decay is functionally active would include consistent paired differences across seeds such as:

- higher turnover under fast decay than no decay;
- younger retrieved evidence under fast decay;
- lower old-trace retrieval share;
- more rank displacement;
- more confirmed resurrections;
- action differences caused by cooling evidence.

A negative result is also informative. If fast, slow, and no-decay arms remain effectively identical under this stress test, decay should be treated as an inactive mechanism until retrieval weighting or environmental structure changes.

## Reproducibility

Run identity is derived from:

```text
code SHA + config hash + arm + seed
```

Each GitHub Actions matrix cell uses a fresh PostgreSQL + pgvector service and exports:

- `experiment.json`
- `retrieval.csv`
- `resurrections.csv`
- `events.jsonl`
- `traces.csv`
- `postgres.sql`

Compact summaries are posted to Experiment 002 issue #9.
