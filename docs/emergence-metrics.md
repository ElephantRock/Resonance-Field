# Emergence Metrics — Resonance Field v0.1

Emergence measurement is a required subsystem, not an optional dashboard. Without it, Resonance Field is only an orchestration framework with biological metaphors.

## 1. Behavioral specialization

For agent `i`, estimate its action distribution `p_i(a)` over a configured observation window.

```text
H_i = -sum_a p_i(a) log p_i(a)
S_i = 1 - H_i / log |A|
```

`H_i` is action entropy. `S_i` is normalized specialization. Higher `S_i` indicates a more concentrated behavioral repertoire.

Track both absolute specialization and its stability across time windows and task families.

## 2. Role emergence

Periodically cluster agents using behavioral features rather than names or prompt labels.

Feature families:

- primitive action frequencies;
- tool usage;
- trace types generated;
- semantic regions visited;
- bidding and delegation behavior;
- challenge frequency;
- retrieval diversity;
- external-data acquisition rate.

Cluster labels are assigned **after** discovery. A cluster may later be interpreted as Forager-like, Synthesist-like, Critic-like, Broker-like, or another role not anticipated by the designers.

Evidence for role emergence strengthens when clusters are stable across windows, predictive of future behavior, and recur across independent seeded runs.

## 3. Consensus concentration

Measure semantic and decision concentration around dominant basins.

A high concentration score does not mean the consensus is wrong. It signals risk of premature convergence and may trigger a bounded exploration subsidy or consensus tax.

Recommended measurements:

- dominant semantic-basin share;
- topic entropy;
- vote concentration;
- independent evidence-source diversity;
- pairwise output similarity.

## 4. Bridge centrality

Build an interaction graph where nodes are agents and/or semantic communities and edges represent meaningful information transfer, adoption, delegation, or trace lineage.

Track agents that connect otherwise weakly connected communities using measures such as betweenness centrality, participation coefficient, and cross-cluster adoption impact.

A high Bridge Score should require successful transfer, not merely high message volume.

## 5. Semantic coverage

Represent explored cognitive territory over embedding space or learned semantic regions.

Track:

- occupied region count;
- density distribution;
- frontier expansion;
- neglected-region persistence;
- coverage change per unit compute.

Exploration bonuses should target low-density regions without rewarding incoherent random wandering.

## 6. Lineage and independent adoption

Every synthesis, crossover, mutation, challenge revision, and resurrected idea maintains explicit lineage.

Metrics:

- lineage depth;
- branching factor;
- survival by generation;
- independent adoption count;
- adoption across agent clusters;
- lineage contribution to verified outcomes.

Independent adoption excludes self-reinforcement and trivial citation.

## 7. Resurrection rate

A resurrection occurs when a cooling, archived, failed, or long-unused trace materially influences new downstream work.

Track:

```text
resurrection_rate = meaningful_resurrections / observation_period
```

Also record time-to-resurrection and whether the resurrected idea changed form through mutation or recombination.

## 8. Strategy persistence

Measure how long distinctive agent strategies remain predictive of behavior.

Persistence should be evaluated across changing tasks. A strategy that appears only because one task dominates the workload is not strong evidence of specialization.

## 9. Plasticity

Plasticity measures ecosystem reorganization after a controlled environmental change.

Possible interventions:

- alter trace half-life;
- change compute scarcity;
- remove a high-centrality agent;
- inject a new task family;
- increase challenge probability;
- change exploration bonus.

Measure recovery time, cluster reformation, semantic redistribution, and performance change.

## 10. Phase-transition detector

A candidate epistemic phase transition is a rapid coordinated change across multiple ecosystem variables.

Monitor normalized changes in:

```text
Delta Consensus
Delta Semantic Centroid
Delta Interaction Modularity
Delta Adoption Graph
Delta Reputation Distribution
```

A transition candidate is emitted when multiple signals exceed configured thresholds within the same time window.

This is an operational detector, not proof of a Kuhnian paradigm shift.

## 11. Core dashboard KPIs

The v0.1 dashboard should expose at minimum:

| KPI | Purpose |
|---|---|
| Behavioral Specialization | Degree of agent behavioral concentration |
| Consensus Concentration | Premature convergence risk |
| Bridge Centrality | Cross-community information transfer |
| Semantic Coverage | Breadth of explored idea-space |
| Lineage Depth | Persistence of idea evolution |
| Independent Adoption | Spread beyond the originating agent |
| Resurrection Rate | Recovery of previously neglected ideas |
| Strategy Persistence | Stability of behavioral niches |
| Plasticity | Reorganization after environmental change |
| Phase Transition Risk | Coordinated structural change detector |

## 12. Primary emergence experiment

**Hypothesis:** agents with common capabilities but persistent local histories, resource scarcity, stigmergic traces, and decentralized task selection will develop statistically distinguishable behavioral niches.

Procedure:

1. Initialize 20 equivalent agents.
2. Give all agents identical primitive capabilities.
3. Assign no occupational roles.
4. Seed heterogeneous problems.
5. Run repeated environment/task cycles.
6. Measure behavior distributions.
7. Cluster without using agent identity as a feature.
8. Test cluster stability over time.
9. Change environmental pressure.
10. Measure reorganization.

A strong result is stable behavioral niches that recur across independent runs despite never being specified in prompts. Temporary differences are a weak result. No persistent differentiation is a negative result. All three outcomes are informative.
