# Critical-Margin Audit

This audit reconstructs only already-executed Resonance Field conditions from Experiments 105–110 and 123–128. It does not introduce Experiment 129, a new seed, feedback strength, perturbation magnitude, perturbation location, mechanism, or treatment family.

The primary hypothesis is that finite microscopic perturbations matter when they cross discrete production decision surfaces. The audit represents local susceptibility by critical perturbation radii. Allocation-relevant radii are computed for the sealed-bid auction argmax, success threshold, and endogenous feedback-domain CDF. Trace gate/ranking geometry is retained as a diagnostic, but code inspection established before reconstruction that the 0.20 confidence-inflation branch is allocation-inert in the frozen environments (`confidence_inflation = 0`) and maximum-trace identity is not consumed by the production bid score.

The secondary hypothesis is margin compression. A decreasing critical radius over time is not labeled self-organized criticality by itself. SOC may be called compatible only if distinct historical trajectories also converge toward a common low-radius regime; the audit does not fit new avalanche laws or introduce a system-size sweep.

The stopping rule is issue #53. No epsilon interpolation run, new perturbation cell, post-hoc decision surface, or Margin Maintenance 129–134 intervention may be added to improve the result.
