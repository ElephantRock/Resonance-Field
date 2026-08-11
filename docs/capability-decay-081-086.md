# Capability Decay Campaign — Experiments 081–086

This campaign tests whether organizational lock-in is caused by persistent private capability rather
than persistent identity, reputation, or market access.

## State separation

The campaign keeps cumulative practice as immutable historical evidence while introducing a separate
`effective_practice` state used for current competence. Only effective practice can decay.

Public verified traces keep their existing substrate decay semantics. Agents remain immortal. No
reputation or access-control intervention is enabled.

## Candidate memory kernels

Experiment 081 compares no decay with exponential inactivity decay, step/threshold decay, and
exponential decay with a bounded retention floor. Experiment 082 removes secondary components from
the best candidate. Experiment 083 varies only the absolute decay timescale around the selected
kernel. Experiments 084–086 freeze the mechanism for stress, replication, and unseen holdout.

## Discovery gate

A candidate must preserve task success within 1.5 percentage points, improve logical early-incumbent
share by at least 2 percentage points, preserve late public knowledge within 10 percentage points,
retain all economic/provenance invariants, require zero identity turnover, and show measurable
erosion of dormant effective capability.

## Clock test

The campaign measures `tau_F`, `tau_D_assoc`, `tau_visit`, and `tau_D_skill`. Before Experiment 086,
the checkpoint predicts whether the unseen holdout lies inside the proposed healthy window:

`tau_visit * margin < tau_D_skill < tau_R` and `tau_F < tau_R`.

The prediction is made before holdout outcomes are evaluated and is stored in the final checkpoint.
