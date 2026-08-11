# Post-Crossing Reconvergence Audit

This audit implements issue #60 using only already-executed Auction Margin Control conditions from Experiments 129–134. It does not introduce Experiment 135, a new seed, radius, epsilon, activation time, decision surface, or treatment arm.

The audit reconstructs the 36 frozen `near_probe` versus `buffered_probe` twin pairs from campaign commit `2a85739603ebac86f451b90733229782c0d45ce0` and verifies them against retained workflow artifacts from run `31530045100` before making any inference.

The primary question is whether transient macro-level divergence is usually absorbed while microscopic state remains distinct. It reuses the exact micro, meso, and macro distance definitions and 3-of-5 threshold rule from the 123–134 campaigns. Recovery is defined as the cycle immediately after the final persistent threshold-crossing window, and the final-regime state is evaluated without changing any distance threshold.

The audit also reports a deliberately low-capacity basin-escape diagnostic. Because only three historical pairs changed final basin, no multivariate classifier or tuned threshold is permitted. A single scalar is reported only if it separates all three basin-disagreement pairs from every basin-agreeing pair without overlap; otherwise the result remains descriptive or non-identifiable.

The stopping rule is issue #60. A failed cross-scale absorption gate must be preserved as a null, and no Experiment 135+ protocol may be created unless the completed audit localizes a distinct causal bottleneck.
