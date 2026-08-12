# Epistemic Substrate Campaign (Experiments 138–141)

This document preregisters the P/S/G/R substrate ablation before outcome-bearing execution.

## Purpose

Test whether a population with identical agents, evidence, tasks, ordering, and budgets acquires greater persistent collective epistemic capability when only the shared substrate is changed.

The campaign distinguishes four arms:

- **138 — Pile (P):** persistent independent reports; no cross-agent reads during discovery; no relational graph.
- **139 — Shared Memory (S):** persistent shared retrieval with provenance, but no relational edges.
- **140 — Provenance Graph (G):** shared memory plus explicit entity/claim/evidence relations and graph traversal.
- **141 — Resonance Field (R):** the provenance graph plus deterministic activation, decay, independent-confirmation reinforcement, contradiction salience, and bridge reinforcement.

The causal estimand is the contribution of substrate structure. The agent population is not a treatment.

## Frozen primary benchmark

The confirmatory benchmark is a deterministic relational world generated from a paired world seed. Each world contains 96 entities, 192 relations, and 64 source packets. Thirty-two identical producer agents receive six observations each under the same assignment and ordering in all four arms.

Each world contains 24 discovery queries and 32 transfer queries. Transfer questions require two-, three-, or four-hop integration and are constructed so that the validated answer is not available in any single producer's local observation set.

All producer-local memory is destroyed before transfer evaluation. Only the arm-specific substrate persists.

No live web access, live LLM call, adaptive prompt change, model swap, or outcome-guided benchmark modification is allowed in Experiments 138–141.

## Cross-arm budget controls

Every arm receives the same maximum six substrate writes per producer, twelve retrieved items per evaluation query, four graph-equivalent traversal hops, and eight reasoning steps per query. A run is invalid if the world, observations, query set, agent capability, execution order, or budget differs across paired arms.

The experiment must also prove that no state object is reused across arms.

## Arm semantics

### Experiment 138 — Pile

Producer reports persist, but producers cannot read other producers during discovery. The transfer evaluator may retrieve from the flat report pile subject to the common retrieval-item budget. No entity-edge structure or provenance graph is materialized.

### Experiment 139 — Shared Memory

Producer observations enter a shared retrievable memory with provenance. Agents may read the shared memory during discovery. Memory remains flat: no explicit graph traversal or relational-edge semantics are available.

### Experiment 140 — Provenance Graph

The same observations are represented as entity/claim/evidence nodes and typed relations with full provenance. Retrieval may traverse the graph subject to the common hop and item budgets. No activation, decay, reinforcement, or bridge weighting is allowed.

### Experiment 141 — Resonance Field

Experiment 140 semantics are retained and deterministic field dynamics are added. Initial activation is 1.0. Activation decays by a factor of 0.97 per epoch, independent confirmations add 0.25, contradiction events add 0.10 salience, and bridge-forming evidence adds 0.20, capped at 3.0. These values are frozen before confirmatory execution.

The field may change retrieval priority; it may not create evidence that was not deposited by the population.

## Primary endpoints

### Transfer accuracy

The fraction of preregistered transfer queries answered correctly after producer death.

### Collective emergence ratio

Let a transfer conclusion be *collective-required* when the validated evidence path spans observations assigned to at least two distinct producer agents and no producer individually received enough observations to derive the answer.

For each world:

`E_collective = correct collective-required conclusions / all collective-required conclusions`

Because transfer questions are constructed to be collective-required, this endpoint isolates whether the substrate preserves and recombines distributed evidence after the contributing agents no longer exist.

## Secondary endpoints

The campaign records evidence coverage, contradiction-resolution F1, bridge recall, provenance completeness, knowledge survival rate, duplicate-work rate, false-synthesis rate, and retrieval items consumed.

Secondary endpoints cannot rescue a failed primary result.

## Confirmatory contrasts

The frozen paired contrasts are:

1. S − P: benefit of shared retrieval over independent reports.
2. G − S: benefit of explicit relational structure over flat shared memory.
3. R − G: incremental benefit of field dynamics over a static provenance graph.
4. R − P: total substrate effect.

All contrasts are paired by world seed. Family-wise alpha is 0.05 with Holm correction. Effect intervals use a 10,000-resample paired bootstrap at 95% confidence.

The total-effect success gate additionally requires R − P to be at least +0.10 absolute on both transfer accuracy and collective emergence ratio.

## Quality gates

A confirmatory result is admissible only if:

- paired worlds, observations, queries, and budgets are byte-equivalent before the substrate adapter is applied;
- producer-local memory is destroyed before transfer;
- no cross-arm substrate state leaks;
- false-synthesis rate is at most 0.05;
- provenance loss is at most 0.01 in graph-bearing arms; and
- all hard benchmark invariants pass.

Instrumentation failures may be repaired only before confirmatory execution and without consulting confirmatory outcomes.

## Cohorts

Instrumentation uses seeds 3101–3108 and is non-inferential. Confirmatory execution uses 64 paired worlds, seeds 3201–3264. The same seed is run through all four arms.

No confirmatory seed may be replaced after outcome inspection.

## Interpretation rule

A positive monotone pattern P ≤ S ≤ G ≤ R is informative, but monotonicity alone is not the success criterion. The preregistered paired contrasts, multiplicity correction, quality gates, and minimum R − P total effects control the decision.

A null result means that, under deterministic equal-capability agents and the frozen benchmark, the added substrate structure did not create the preregistered persistent collective capability. A later stochastic LLM/web replication may test external validity but may not retroactively rescue Experiments 138–141.

## Next implementation step

Implement one benchmark generator, one immutable observation schedule, one evaluator, and four substrate adapters behind a common interface. The adapter boundary must be the only treatment-specific code path during the confirmatory campaign.
