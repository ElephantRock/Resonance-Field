# Demand-Structure Campaign — Experiments 099–104

## Question

Does Resonance Field lock-in arise from the temporal structure of demand itself?

This campaign tests:

> same exogenous task packets + same agents + same market rules + different temporal order → different organizational trajectory

The campaign does not alter production reputation, capability learning, candidate generation, sealed-bid scoring, settlement, public traces, or agent lifetime.

## Experimental intervention

Each source cycle inside a regime is treated as an **exogenous task packet** containing task domain, regime-dependent required skill, requester slot, deterministic candidate set, confidence/price/speed noise draws, and outcome/evidence-noise draws.

A schedule maps every target cycle to one source-cycle packet. The mapping is constrained to be a permutation inside the same regime, so task composition and regime-dependent semantics are unchanged. Only packet order changes.

Tested schedules:

- `baseline` — original deterministic order;
- `shuffled` — deterministic within-regime permutation;
- `interleaved` — minimizes adjacent same-domain demand;
- `paired` — moderate persistence with two-task chunks;
- `blocked` — groups same-domain demand into long runs.

Every cell records append-only `demand_schedule_observations` with target/source cycle, task ID, requester, candidate slots, schedule mode, and a SHA-256 fingerprint of the source packet.

## Sequence

| Experiment | Test |
|---|---|
| 099 | Temporal-order screen |
| 100 | Exact-task decomposition |
| 101 | Persistence response |
| 102 | Cluster → interleave → cluster reversal |
| 103 | Independent replication |
| 104 | Unseen holdout |

## Discovery gates

A positive candidate must preserve all economic/provenance invariants, preserve the exact per-regime task multiset, require zero identity turnover and no reputation intervention, keep task success within 1.5 percentage points of control, reduce logical early-incumbent share by at least 2 percentage points, preserve late public knowledge within 10 percentage points, and materially change demand persistence.

Final validation additionally requires exact-task decomposition, persistence response, within-run reversal, independent replication, unseen holdout, and agreement with the predeclared re-lock prediction.

## Interpretation boundary

A positive result establishes that exogenous demand sequencing is sufficient to generate or release organizational path dependence under the tested conditions. A null result retires exogenous demand ordering and moves the causal target to **endogenous demand feedback**: completed work changing which tasks the system generates next.

Production behavior remains unchanged and reputation-neutral regardless of outcome.
