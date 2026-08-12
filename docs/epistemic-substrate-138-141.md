# Epistemic Substrate Campaign (Experiments 138–141)

This document preregisters the P/S/G/R substrate ablation before outcome-bearing execution.

## Purpose

Test whether a population with identical agents, evidence, tasks, ordering, and operation budgets acquires greater persistent collective epistemic capability when only the shared substrate is changed.

The campaign distinguishes four arms:

- **138 — Pile (P):** persistent independent reports with no relational index or provenance graph.
- **139 — Shared Memory (S):** persistent flat shared retrieval with provenance, but no relational edges.
- **140 — Provenance Graph (G):** shared memory plus explicit entity/claim/evidence relations and keyed graph retrieval.
- **141 — Resonance Field (R):** the provenance graph plus deterministic activation, decay, independent-confirmation reinforcement, contradiction salience, and topology-derived bridge reinforcement.

The causal estimand is the contribution of substrate structure. The agent population is not a treatment.

## Frozen primary benchmark

The confirmatory benchmark is a deterministic relational world generated from a paired world seed. Each world contains 96 entities, four relation types, 192 **observation claims**, and 64 source packets. Thirty-two identical producer agents receive six observations each under the same assignment and ordering in all four arms.

Each world contains 24 discovery queries and 32 transfer queries. Transfer questions require two-, three-, or four-hop integration and are constructed so that the validated answer is not available in any single producer's local observation set. Source-packet assignment is rejected and regenerated whenever one producer could solve a complete transfer path alone.

All producer-local memory is destroyed before transfer evaluation. Only the arm-specific substrate persists.

No live web access, live LLM call, adaptive prompt change, model swap, or outcome-guided benchmark modification is allowed in Experiments 138–141.

## Frozen evidence mixture

The benchmark deliberately contains evidence regimes that prevent a field policy from winning merely by preferring either recency or repetition.

Among required transfer relations, each paired world contains:

- 8 **fast-change** relations: two stale incorrect observations followed by a current true observation;
- 8 **slow-change** relations: two moderately stale incorrect observations followed by a current true observation;
- 8 **recent-rumor** relations: two earlier true confirmations followed by one current incorrect observation; and
- 24 **stable-confirmation** relations: two true observations at late epochs.

Remaining required relations receive a current true observation. Remaining observation capacity is filled with true distractor claims on non-required relation keys. The final epoch is 40.

This mixture is frozen before any confirmatory seed is evaluated.

## Cross-arm operation budget

Every arm has the same ceiling of six substrate writes per producer, 12 retrieval-operation units per evaluation query, four graph-equivalent traversal hops, and eight reasoning steps per query.

Representation costs are part of the treatment and are frozen:

- extracting one matching atomic claim from an opaque report pile costs 3 units;
- retrieving one candidate claim from shared flat memory costs 1 unit; and
- retrieving one claim from keyed graph adjacency costs 1 unit.

The common 12-unit ceiling is therefore identical, while the substrate determines how efficiently evidence can be located under that ceiling. This campaign does **not** claim equal raw-item scan cost across representations; search efficiency is one of the mechanisms being tested.

A run is invalid if the world, producer observations, transfer queries, reasoning ceiling, or total operation budget differs across paired arms. No mutable substrate state may be reused across arms.

## Arm semantics

### Experiment 138 — Pile

Producer reports persist as opaque report collections. No relational index or provenance graph is materialized. A conflicting set of extracted report claims causes abstention because the pile does not expose provenance structure sufficient for conflict resolution.

### Experiment 139 — Shared Memory

Producer observations enter a shared flat memory with provenance and subject-level retrieval. Retrieval must consume subject candidates before relation filtering, so flat-memory search can spend budget on irrelevant relations for the same subject. Conflict resolution is conservative: a unique support majority is accepted only when its latest evidence is not older than the alternatives; otherwise the system abstains.

### Experiment 140 — Provenance Graph

The same observations are represented as keyed entity/claim/evidence relations with full provenance. Retrieval uses exact `(subject, relation)` adjacency under the common operation budget. Conflict resolution is identical to Experiment 139. No activation, decay, reinforcement, or bridge weighting is allowed.

### Experiment 141 — Resonance Field

Experiment 140 semantics are retained and deterministic field dynamics are added. Initial activation is 1.0. Activation decays by a factor of 0.97 per epoch, independent confirmations add 0.25, contradiction events add 0.10 salience, and topology-derived bridge evidence adds 0.20, capped at 3.0.

Bridge salience is computed only from the deposited claim topology. The bridge detector accepts claims as its sole input; transfer queries never enter bridge computation.

When activation and support disagree, or when a reinforced majority is older than a fresher alternative, field activation may override only when the activation margin is at least 0.60. Otherwise the field abstains. The 0.60 margin is frozen before confirmatory execution.

The field may change retrieval/selection priority; it may not invent evidence that was not deposited by the population.

## Discovery-query role

Discovery queries are deterministic benchmark probes and introduce no new facts or treatment-specific writes. The primary causal endpoint is post-death transfer from the persisted substrate. The arm capability flags for discovery-time shared reads are retained in configuration metadata, but no arm is allowed to change the frozen producer observation assignment through discovery-query feedback in Experiments 138–141.

This prevents discovery-time adaptation from becoming a second causal treatment.

## Primary endpoints

### Transfer accuracy

The fraction of preregistered transfer queries answered correctly after producer death.

### Collective emergence ratio

Let a transfer conclusion be *collective-required* when the validated evidence path spans observations assigned to at least two distinct producer agents and no producer individually received enough observations to derive the answer.

For each world:

`E_collective = correct collective-required conclusions / all collective-required conclusions`

A conclusion counts as collectively correct only when the predicted target is correct, the recovered path exactly matches the validated truth path, and the recovered evidence path contains contributions from at least two producer agents.

Because all transfer questions are constructed to be collective-required, this endpoint isolates whether the substrate preserves and recombines distributed evidence after the contributing agents no longer exist.

## Secondary endpoints

The campaign records evidence coverage, contradiction-resolution F1, bridge recall, provenance completeness, knowledge survival rate, duplicate-work rate, false-synthesis rate, and retrieval operation units consumed.

Secondary endpoints cannot rescue a failed primary result.

## Confirmatory contrasts and inference

The frozen paired contrasts are:

1. S − P: benefit of shared indexed retrieval/provenance over independent opaque reports.
2. G − S: benefit of exact relational structure over flat shared memory.
3. R − G: incremental benefit of field dynamics over a static provenance graph.
4. R − P: total substrate effect.

Each contrast is evaluated on both primary endpoints, producing one family of **8 primary hypothesis tests**. Family-wise alpha is 0.05 and all eight raw p-values are corrected together with Holm's procedure.

For each paired contrast and endpoint:

- the effect estimate is the mean within-world treatment-minus-control difference;
- the 95% effect interval is a paired percentile bootstrap with 10,000 resamples; and
- the raw two-sided p-value is a paired sign-flip randomization test with 100,000 resamples.

Randomization is deterministic. The frozen campaign randomization seed is `138141`; independent per-test bootstrap and sign-flip streams are derived from that seed plus the endpoint/contrast label through SHA-256.

The campaign-level success rule is deliberately stronger than simple monotonicity. Both R − P primary effects must simultaneously satisfy all three conditions:

1. absolute effect at least +0.10;
2. Holm-adjusted p-value below 0.05; and
3. 95% paired-bootstrap lower bound above zero.

Failure of either primary R − P endpoint means the campaign does not meet the preregistered success criterion. Secondary endpoints and intermediate contrasts cannot rescue that failure.

## Quality gates

A confirmatory result is admissible only if:

- paired worlds, observations, transfer queries, and total operation ceilings are identical before the substrate adapter is applied;
- producer-local memory is destroyed before transfer;
- no cross-arm substrate state leaks;
- false-synthesis rate is at most 0.05;
- provenance loss is at most 0.01 in graph-bearing arms; and
- all hard benchmark invariants pass.

Instrumentation failures may be repaired only before confirmatory execution and without consulting confirmatory outcomes.

## Cohorts and statistical seal

Instrumentation uses seeds 3101–3108 and is non-inferential. Confirmatory execution uses 64 paired worlds, seeds 3201–3264. The same confirmatory world seed will be run through all four arms.

The instrumentation CLI and workflow enumerate only the instrumentation cohort. They write `inferential: false` and `confirmatory_seeds_evaluated: false` into the evidence artifact.

The sealed confirmatory CLI additionally requires the literal seal `OPEN-138-141-CONFIRMATORY` and a validated instrumentation artifact whose campaign name, configuration hash, and instrumentation seed cohort exactly match the current frozen configuration. It refuses evidence that is inferential, failed instrumentation gates, or claims that confirmatory seeds were previously evaluated.

No confirmatory seed may be replaced after outcome inspection.

## Pre-confirmatory instrumentation refinements

The initial campaign scaffold froze the four-arm causal question, primary endpoints, confirmatory contrasts, and disjoint instrumentation/confirmatory cohorts before executable instrumentation existed.

Non-inferential work on seeds 3101–3108 then exposed three mechanical defects:

1. an equal raw-item retrieval interpretation drove the report pile into an artificial floor;
2. source-packet shuffling could occasionally place a complete truth path inside one producer's packet allocation; and
3. an unconstrained activation resolver could over-trust a reinforced but stale majority.

Before any seed in 3201–3264 was generated or evaluated, the executable protocol was therefore frozen to the representation-cost operation budget above, rejection sampling for collective-required packet assignment, the balanced evidence-regime mixture, and the 0.60 contradiction-override margin.

These changes are instrumentation fixes and benchmark-definition refinements. Results from 3101–3108 are not part of confirmatory inference and cannot be reported as evidence for the scientific hypothesis.

**No confirmatory seed has been evaluated during protocol refinement.**

## Interpretation rule

A positive monotone pattern P ≤ S ≤ G ≤ R is informative, but monotonicity alone is not the success criterion. The preregistered eight-test Holm family, paired inference, quality gates, and dual-primary R − P success rule control the decision.

A null result means that, under deterministic equal-capability agents and the frozen benchmark, the added substrate structure did not create the preregistered persistent collective capability. A later stochastic LLM/web replication may test external validity but may not retroactively rescue Experiments 138–141.

## Current execution boundary

The branch now contains the deterministic world generator, immutable observation schedule, four substrate adapters, transfer evaluator, frozen configuration loader, mechanical tests, frozen confirmatory statistics, an instrumentation-only CLI/workflow, and a sealed confirmatory CLI.

Confirmatory execution is not invoked by the instrumentation workflow. The 64-world cohort may be opened only after this exact code/configuration/documentation state passes the repository CI and the read-only instrumentation gate, and after a matching validated instrumentation artifact exists for the same configuration hash.
