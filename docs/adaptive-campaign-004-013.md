# Adaptive Campaign — Experiments 004–013

This campaign executes ten consecutive Resonance Field experiments. Experiment 004 is fixed by the result of Experiment 003; every subsequent experiment is chosen from the preceding experiment's measured result.

## Starting result

Experiment 003 established that persistent contextual Beta reputation is an active organizational mechanism but not yet a production-quality allocation signal. Raw persistent reputation increased behavioral continuity and specialization, especially when substrate traces decayed quickly, while also increasing stale-incumbent retention after a regime shift. It did not improve overall delegation success.

The campaign therefore asks whether the organizational memory supplied by reputation can be made **fresh, contextual, and plastic** without losing task quality.

## Scientific boundary

The campaign is a deterministic simulation laboratory, not a replacement for the PostgreSQL reputation ledger established and integration-tested by Experiment 003. The campaign isolates the allocation-policy layer so many sequential interventions can be evaluated cheaply and reproducibly before any scorer is promoted into the production market.

All simulated agents begin equivalent. There are no role, profession, or species assignments. Differentiation can arise only from task exposure, practice, finite trace evidence, market selection, and reputation evidence.

Reputation remains evidence, not currency. It cannot transfer Compute Credits and cannot modify safety policy.

## Shared environment

Training experiments use:

- 20 initially equivalent agents;
- six task domains / skill basins;
- 240 cycles;
- a regime shift every 60 cycles;
- each shift rotates the skill required by every domain;
- five paired seeds: 101, 202, 303, 404, 505;
- two trace-memory regimes: 4-cycle and 30-cycle half-lives;
- eight deterministic candidate agents per task.

A successful task creates fresh skill evidence. The most recent successful evidence decays exponentially:

\[
E(t)=0.9\,2^{-\Delta t/h}
\]

Practice raises an agent's probability of success in the exercised skill basin, so specialization can emerge from history rather than declaration.

Candidate bids use the production market's baseline weights:

\[
BidScore=0.45\,Confidence+0.35\,PriceEfficiency+0.20\,Speed
\]

The campaign adds a reputation adjustment only for reputation-enabled policies.

## Reputation policy family

A policy may vary:

- reputation influence weight;
- freshness half-life;
- domain, required-skill, or blended context;
- domain/skill blend ratio;
- minimum evidence-mass gate;
- negative-evidence weight;
- partial domain-memory reset when a regime changes.

The underlying evidence remains Beta-style success/failure evidence. Freshness does **not** delete old evidence; it attenuates its present allocation influence toward the neutral score of 0.5.

For a raw posterior mean \(R\), freshness factor \(F\), and evidence-mass factor \(M\):

\[
R_{active}=0.5+(R-0.5)FM
\]

## Metrics

Each arm reports:

- task success rate;
- agent/domain mutual information;
- mean agent specialization;
- mean domain winner HHI;
- early post-shift share retained by previous incumbents;
- winner replacement rate.

The structural score is:

\[
S=0.60\frac{MI}{\log |D|}+0.40\,Specialization-0.20\,HHI
\]

The utility used only for tie-breaking among feasible policies is:

\[
U=Success+0.10S+0.05Replacement-0.08Incumbency
\]

## Hard selection constraints

Emergent structure is not allowed to justify materially worse competence or lock-in.

A policy is eligible to become the center of the next experiment only when:

1. mean success is no more than 1 percentage point below the no-reputation control; and
2. early post-shift incumbent share is no more than 5 percentage points above control.

Among eligible policies, the campaign chooses the highest utility deterministically. If no policy is eligible, the best available fallback is selected, which may be the no-reputation control.

## Sequential experiment logic

### Experiment 004 — freshness screen

Fixed question:

> Can freshness-aware reputation preserve useful organizational memory while reducing stale-incumbent retention under repeated context shifts?

Arms include no reputation, raw persistent reputation, and several domain-reputation freshness horizons.

The winning policy and its dominant remaining failure mode determine Experiment 005.

### Experiments 005–011 — adaptive local search

Each experiment tests exactly one previously untested policy dimension around the policy selected by the prior experiment.

The dimension order is **not fixed in advance**. The previous result is classified by dominant remaining failure:

- **plasticity:** stale-incumbent excess is too high;
- **quality:** success falls materially below control;
- **structure:** quality and plasticity are acceptable but organization remains weak;
- **calibration:** basic quality/plasticity/structure criteria are satisfied, so evidence shaping is investigated.

That classification determines which untested policy dimension is examined next. A null result is still informative: the incumbent policy remains selected and the campaign moves to the next most relevant dimension.

### Experiment 012 — adaptive stress test

Experiment 011's remaining failure mode selects the stress environment:

- plasticity failure → faster regime shifts;
- quality failure → thinner candidate market;
- structure failure → trace-memory collapse;
- calibration state → mixed memory pressure.

The stress experiment may retune the policy using the dimensions most relevant to that failure.

### Experiment 013 — holdout validation

Experiment 012 chooses the holdout shock schedule from its remaining failure mode. Experiment 013 then evaluates the final selected policy on unseen seeds:

606, 707, 808, 909, 1001.

The holdout uses a different horizon, shift cadence, trace-memory set, and candidate count from training. The final policy is compared with both no reputation and raw persistent reputation.

Validation requires:

- the same hard quality/plasticity constraints used during training; and
- final utility no more than 0.005 below the no-reputation control.

## Evidence artifacts

The workflow produces:

- `campaign.json` — complete campaign graph and final verdict;
- `experiment-004.json` through `experiment-013.json`;
- `experiment-arms.csv` — one row per experiment arm;
- `cells.csv` — per-seed/per-trace-memory evidence;
- `run-metadata.json` — config hash and commit metadata.

Each experiment posts its question, selected arm, measured metrics, decision, and next experiment focus to GitHub issue #13. The final comment records the selected policy and holdout verdict.

## Interpretation rule

Passing this campaign would not prove that a reputation scorer should be permanently fixed. It would establish a specific policy as a stronger candidate for integration testing in the real task market. Failing the holdout would be equally useful evidence: the production market should remain reputation-neutral while the next mechanism is investigated.
