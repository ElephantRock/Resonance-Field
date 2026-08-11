# Auction Margin Control Campaign — Experiments 129–134

This campaign prospectively tests the sealed-bid auction argmax decision surface identified by the completed critical-margin audit in issue #53. It does not test self-organized criticality: the audit supported decision-surface attribution but did not support endogenous margin compression or SOC.

At one preregistered activation auction, an experiment-local score provider places the nearest losing bid at a fixed positive radius from the natural winner and optionally applies the same frozen `epsilon=0.10` score-equivalent confidence probe. The near arm uses radius `0.01`; the buffered arm uses radius `1.00`. Margin placement alone must preserve the natural winner. The provider is zero outside the activation auction and all production symbols are restored after each cell.

Experiments 129–130 establish instrumentation and local causal specificity. Experiment 131 tests whether the one induced discrete crossing propagates to persistent organizational divergence. Experiments 132–134 test activation-time transfer, independent replication, and an unseen 15-cycle regime environment without refitting.

The canonical protocol, seeds, thresholds, stopping rule, and interpretation gates are frozen in GitHub issue #57. No radius, probe magnitude, seed, activation time, distance threshold, or target rule may be added after Experiment 129 outcomes are observed. Production remains unchanged and reputation-neutral.
