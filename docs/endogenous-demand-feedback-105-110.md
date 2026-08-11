# Endogenous Demand Feedback — Experiments 105–110

This campaign tests whether Resonance Field can acquire organizational path dependence through a closed **organization → environment → organization** loop.

The production simulator currently chooses each task domain from a deterministic seed/cycle hash. Experiments 105–110 leave the production market, agents, reputation policy, candidate generation, bid draws, capability learning, settlement, traces, and matching objective unchanged. An experimental controller can only replace the next task-domain index.

For each cycle, the controller counts successful completions by domain over the previous 12 completed cycles. At feedback strength `λ`, the normal exogenous domain is used with probability `1-λ`; otherwise a domain is sampled from the empirical distribution of those recent successful completions. No pseudocount is used, so feedback is inert before the first success.

A specificity ablation rotates the source domain of each successful completion by one domain before updating the feedback state. This preserves success timing while breaking same-domain alignment.

The preregistered sequence is:

- 105: feedback screen at `λ ∈ {0, .25, .50, .75}`;
- 106: aligned closed loop versus permuted-source ablation;
- 107: frozen bounded strength response; no later strength sweep;
- 108: feedback on → off → on without resetting agents or knowledge;
- 109: independent replication on seeds 404 and 505;
- 110: unseen holdout on seeds 707, 808, and 909.

A family-level discovery requires the complete chain: invariants, quality preservation, at least a two-percentage-point active logical-incumbency increase, feedback override rate at least 0.10, causal specificity, bounded response, reversal, replication, and unseen prediction agreement.

Implementation uses a scoped experimental wrapper around the existing lifecycle runner. `_domain_index` is restored after each cell, and the trace repository is wrapped only to observe successful verified outcomes after settlement. This keeps the production lifecycle runner itself unchanged.

Canonical preregistration: issue #39.
