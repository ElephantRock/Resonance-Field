# Lifecycle & Succession Campaign — Experiments 063–074

## Research question

Experiments 001–062 treated market-active agent identity as effectively immortal. Trace energy decayed, reputation influence could be reset or gated, and task/skill mappings changed, but incumbent actors never had to leave the competitive population.

The next causal question is:

> Does finite competitive lifetime restore organizational plasticity while preserving useful public knowledge?

The campaign distinguishes three persistence layers:

- **competitive persistence** — whether an identity can keep bidding and winning;
- **identity persistence** — whether the actor still exists after leaving ordinary competition;
- **cultural persistence** — whether traces authored by prior generations continue shaping retrieval.

The primary hypothesis is competitive exit, not literal destruction.

## Experimental sequence

1. **063 — immortal baseline.** Reproduce the high-practice (`g=0.14`) regime under immortal identities.
2. **064 — fixed competitive exit.** Fresh replacement after a fixed active lifetime.
3. **065 — stochastic exit.** Matched expected lifetime without synchronized cohort replacement.
4. **066 — lifetime response.** Compare several fixed lifetimes and determine whether turnover is causally material.
5. **067 — death vs retirement.** Hold the exit schedule constant and test whether literal identity destruction matters after bidding ends.
6. **068 — retired advisory access.** Permit explicit consultation of retired identities without restoring bidding rights.
7. **069 — reputation independence.** Repeat the selected lifecycle with reputation removed.
8. **070 — rapid regime shift.** Test lifecycle robustness when the task-to-skill mapping changes faster.
9. **071 — cultural persistence.** Compare the ordinary public substrate with lineage-diversified retrieval.
10. **072 — fast-learning synthesis.** Ask whether `g=0.14` can retain task quality while eliminating the immortal-population plasticity penalty.
11. **073 — independent replication.**
12. **074 — unseen holdout** on new seeds, a different remap period, and an unseen lifecycle timing.

## Lifecycle semantics

Population size remains constant. On competitive exit:

- the retiring identity stops bidding;
- its remaining compute balance is reclaimed to the treasury;
- a fresh successor is registered in the same logical lineage slot;
- the successor receives baseline credits;
- reputation is neutral;
- practice is zero;
- private history is not inherited;
- public traces remain in the shared substrate.

The public substrate is therefore allowed to preserve culture after actor exit.

### Retirement vs death

`retirement` and `death` deliberately share the same competitive-exit schedule. Retirement keeps the historical identity conceptually available; death does not. Experiment 068 adds a separate advisory mechanism so consultation can be tested without conflating it with bidding eligibility.

## Cultural persistence

The lifecycle runner makes the public trace field weakly causally relevant to bidding confidence in **every arm**, using the same configured public-trace weight. This is necessary to test whether successors are epistemically shaped by predecessors.

Experiment 071 changes only retrieval aggregation:

- ordinary retrieval uses the strongest relevant public trace;
- diversified retrieval averages the strongest traces across multiple lineages.

No trace is deleted and successful lineages are not automatically penalized.

## Primary lifecycle metrics

- `identity_early_incumbent_share` — post-shift persistence of concrete agent UUIDs rather than logical slots;
- `identity_replacement_rate` — whether domain incumbents are replaced by new identities;
- `turnover_rate` and `mean_active_age`;
- `public_knowledge_coverage` — fraction of post-exit contexts with retrievable public evidence above threshold;
- `retired_trace_retrieval_share` — how much retrieved evidence still comes from exited actors;
- `cultural_lineage_hhi` — concentration of top retrieved traces by lineage;
- ordinary task success, winner HHI, specialization, calibration, prices, and active-credit Gini.

## Discovery gate

Competitive exit is considered causally meaningful only if a finite-lifecycle arm:

1. preserves task success within the existing tolerance;
2. materially reduces identity incumbency or winner concentration;
3. preserves public knowledge coverage;
4. preserves all ledger, escrow, bid immutability, reputation non-spendability, and score-provenance invariants.

The final campaign succeeds only if the selected lifecycle also survives independent replication and Experiment 074's unseen holdout.

## Scientific boundary

This campaign uses **exogenous lifecycle rules** for causal clarity. It does not yet claim emergent mortality. Bankruptcy, ecological starvation, voluntary retirement, lineage creation, or other endogenous exit mechanisms belong to a later campaign if succession itself proves causal.

Production remains reputation-neutral regardless of outcome.
