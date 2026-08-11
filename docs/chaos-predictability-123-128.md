# Chaos / Predictability-Decay Campaign — Experiments 123–128

This campaign tests whether Resonance Field exhibits bounded sensitive dependence under native microscopic perturbations, and whether any such sensitivity propagates from microscopic agent/evidence state to organizational observables.

The preregistration is canonical in GitHub issue #48. The implementation does not alter production behavior; each chaos cell patches experiment-local hooks and restores production symbols after the cell.

## Perturbations

- Cycle-5 relative confidence perturbation on the first deterministic candidate bid.
- First post-cycle-5 successful verified trace energy perturbation.
- +1-cycle feedback timing sensitivity control.
- Embedding negative control; the current verified-outcome path is expected to expose no embedding.

The continuous epsilon grid is fixed at `1e-6, 1e-4, 1e-2, 1e-1, 1.0`. This is a perturbation-size / basin-radius test, not an edge-of-chaos parameter sweep.

## Divergence

Distances are preserved separately at microscopic, mesoscopic, and macroscopic scales. Forecast horizon is the first persistent crossing of the frozen scale threshold. Chaos-compatible scaling requires decreasing forecast horizon with increasing log epsilon, at least three distinct finite horizons, bounded nontrivial saturation, independent replication, and holdout transfer.

A macroscopic chaos claim additionally requires organizational threshold crossing and basin disagreement among small-epsilon twins. Otherwise the canonical result is classified as microscopic chaos with organizational predictability, basin-boundary sensitivity, instability, or no replicated predictability decay.

## External boundary

Issue #42 remains blocked during 123–128. Only a fully validated organizational-chaos result can unblock it for redesign/preregistration as a sustained causally independent perturbation source; it does not authorize execution of the old one-shot boundary design.
