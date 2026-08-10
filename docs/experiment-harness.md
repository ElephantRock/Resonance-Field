# Experiment Harness v0.1

The experiment harness turns Resonance Field from an architecture into a reproducible artificial-cognitive-ecosystem laboratory.

## Execution model

GitHub is the persistent laboratory record. GitHub Actions supplies disposable experiment compute. Every run starts from a fresh PostgreSQL + pgvector service, applies the canonical migrations, executes a seeded experiment, exports raw evidence, and then discards the runner.

A run is identified by:

```text
code SHA
+ config hash
+ ablation
+ seed
= deterministic run ID
```

The database stores this identity in `experiment_runs`. `experiment_agents` records the exact population membership and slot assignment for that run.

## First experiment

The canonical protocol is `configs/experiments/first-emergence.json`:

- 20 initially equivalent agents;
- 40 environment cycles;
- eight heterogeneous topic regions;
- equal initial compute credits;
- shared substrate and common primitive action vocabulary;
- no occupational role labels;
- action-level compute charges;
- snapshots every 10 cycles.

The first comparison has three arms:

```text
full
no_market
no_decay
```

The GitHub Actions matrix runs each arm with seeds `101`, `202`, and `303`, producing nine independent datasets.

## Deterministic policy phase

The first harness uses `SeededExperimentPolicy`, not an external LLM. Every agent receives the same policy implementation and cost schedule. The policy has no fixed per-agent occupational parameters. Its action selection is a deterministic function of the global seed, cycle, agent slot, topic exposure, retrieved substrate state, available market work, and current credit balance.

This phase validates the laboratory apparatus before model-provider variability is introduced. It is not evidence about LLM emergence by itself.

A later model router can replace this policy while retaining the same run identity, evidence schema, metering, artifact contract, and ablation machinery.

## Compute scarcity

Experiment action costs are versioned in the experiment config. The controller creates one `experiment_compute_sink` account per run. Each metered action transfers credits from the acting agent to that sink through the existing double-entry ledger.

The action, decision provenance, and compute charge execute inside one outer PostgreSQL unit of work. If metering fails, the action and provenance roll back with it.

`ABSTAIN` and `SLEEP` may remain zero-cost terminal options, allowing an agent with depleted credits to stop acting without minting resources.

## Evidence tables

```text
experiment_runs
experiment_agents
experiment_action_costs
experiment_snapshots
```

These augment, rather than replace, the canonical substrate, market, ledger, and decision-event tables.

## Initial metrics

The harness computes:

- normalized behavioral specialization;
- agent/action mutual information;
- compute-credit Gini coefficient;
- ending-balance Gini coefficient;
- total compute spent;
- task posting/completion/cancellation counts;
- bid count;
- generated trace count;
- synthetic topic coverage.

For agent `i`:

```text
H_i = -sum_a p_i(a) log p_i(a)
S_i = 1 - H_i / log |A|
```

The denominator uses the complete primitive action vocabulary, not only actions observed in one run.

`topic_coverage` is explicitly a synthetic-harness proxy. It is not a general semantic-coverage metric and should be replaced by embedding-space coverage when model-generated content enters the experiment.

## Snapshots

Metrics are persisted periodically in `experiment_snapshots`. This allows later analysis of trajectories rather than only endpoint comparisons.

## Artifacts

Each GitHub Actions matrix cell uploads:

```text
experiment.json
agents.csv
events.jsonl
tasks.csv
traces.csv
postgres.sql
```

The PostgreSQL dump is the canonical replay/debug artifact. The JSON/CSV files make cross-run analysis inexpensive.

## Workflow

`.github/workflows/experiment.yml` supports manual execution and also runs once when the workflow is first merged to `main`. A standard execution yields nine artifacts:

```text
full       × 101 202 303
no_market  × 101 202 303
no_decay   × 101 202 303
```

The experiment workflow is intentionally separate from CI. CI answers whether the software is correct enough to run; the experiment workflow produces scientific evidence.

## Interpretation boundary

Stable specialization in this deterministic phase demonstrates that the environmental machinery can produce differentiated trajectories under common capabilities. It does **not** establish that an LLM population self-organizes in the same way.

The next experimental phase replaces the seeded policy with a provider-neutral cognitive model while holding the rest of the protocol constant. That comparison is itself an important ablation.
