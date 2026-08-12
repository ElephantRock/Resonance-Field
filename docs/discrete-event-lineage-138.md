# Experiment 138 — Discrete Causal-Event Lineage Instrumentation

Experiment 138 is an **instrumentation-only** test of whether one controlled auction-winner divergence can be represented as the root of a deterministic downstream causal-event DAG.

The protocol is frozen in GitHub issue #70, including the pre-execution clarification freeze. This implementation does not rescue Experiments 135–137, does not fit a branching model, and does not authorize Experiments 139–141.

## Calibration-only execution

This first implementation executes **only calibration seeds 3101–3106** under schema `v1`:

- matched natural-control and one-kick twin;
- one validated near-surface winner flip at cycle 36;
- 90-cycle horizon;
- primary lineage window cycles 36–53, with downstream capture evaluated on cycles 37–53;
- eight frozen event classes;
- parents derived mechanically from causally used read/write provenance;
- multi-parent DAGs are retained rather than coerced into trees.

Held-out seeds `3107–3112` are neither executed nor exposed by the calibration workflow.

## Calibration readiness

The v1 schema is calibration-ready only if all root/invariant checks pass and, pooling downstream divergent events from cycles 37–53 across seeds 3101–3106:

- at least 90% have a non-empty mechanically derived parent set;
- orphan share is at most 10%;
- every seed with attributable downstream events has a root-directed path to at least 90% of those events;
- no lineage node or edge exists before the imposed root.

If v1 is not calibration-ready, issue #70 permits at most two corrective instrumentation revisions, v2 and v3, limited to demonstrable provenance/keying/plumbing defects. The ontology, window, thresholds, seeds, intervention, and parent definition cannot change. If v3 still fails, Experiment 138 stops before held-out validation.

## Outputs

The calibration artifact retains:

- `experiment-138-calibration.json`;
- `experiment-138-event-nodes.csv`;
- `experiment-138-parent-edges.csv`;
- `experiment-138-pair-summary.csv`;
- `experiment-138-schema-manifest.json`;
- `experiment-138-calibration-report.md`.

No calibration result is a validation result. Passing calibration only permits a later schema-freeze step followed by one-time held-out validation under the already-preregistered gate.
