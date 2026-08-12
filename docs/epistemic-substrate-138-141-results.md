# Epistemic Substrate Experiments 138–141 — Confirmatory Results

## Status

**Preregistered campaign success: PASS.**

The sealed 64-world confirmatory cohort passed all hard quality gates and satisfied the preregistered campaign-level success rule on both primary endpoints.

These results are from the first outcome-bearing execution of confirmatory seeds 3201–3264. No confirmatory seed was evaluated during instrumentation or protocol refinement.

## Sealed execution record

- Branch: `experiment/epistemic-substrate`
- Pull request: #72
- Confirmatory workflow run: `31596674999`
- Branch-head commit that opened the confirmatory workflow: `024361d59262bc02eeb144c9e3284446abcc70d1`
- GitHub pull-request merge-ref SHA recorded inside the runner: `c2c289dfe30d04c016c959611c438eeacbb904b4`
- Confirmatory artifact: `epistemic-substrate-138-141-confirmatory`
- Artifact SHA-256 digest: `3813b917cafb7b485aff0006a59e4d2d6b3f01df066458ff24d9dc1327e0c35b`
- Frozen canonical configuration hash: `9ef9b64aa752a026f9cfe9f29bad49836d5a56eed4e8830138c5f17813ef9520`
- Confirmatory worlds: 64 paired seeds, `3201–3264`
- Arms per world: Pile (138), Shared Memory (139), Provenance Graph (140), Resonance Field (141)

The sealed artifact contains `confirmatory.json`, the matching non-inferential `instrumentation.json`, `github-sha.txt`, and `seal-manifest.sha256`.

## Primary arm means

| Arm | Experiment | Transfer accuracy | Collective emergence ratio |
|---|---:|---:|---:|
| Pile (P) | 138 | 0.259277 | 0.259277 |
| Shared Memory (S) | 139 | 0.304199 | 0.304199 |
| Provenance Graph (G) | 140 | 0.367188 | 0.367188 |
| Resonance Field (R) | 141 | **0.515137** | **0.515137** |

The observed ordering was monotone:

`P < S < G < R`

R improved the primary score by **+0.255859 absolute** over P, nearly doubling the baseline score under the same frozen world/query/operation ceilings.

## Frozen primary contrasts

All effects below are paired treatment-minus-control differences across the 64 world seeds. Raw p-values come from the frozen 100,000-resample two-sided paired sign-flip test. All eight primary tests were corrected together with Holm's procedure. Confidence intervals are frozen 10,000-resample paired percentile-bootstrap 95% intervals.

### Transfer accuracy

| Contrast | Control mean | Treatment mean | Effect | 95% CI | Raw p | Holm-adjusted p |
|---|---:|---:|---:|---:|---:|---:|
| S − P | 0.259277 | 0.304199 | +0.044922 | [0.033691, 0.055664] | 0.000010 | 0.000080 |
| G − S | 0.304199 | 0.367188 | +0.062988 | [0.052246, 0.074219] | 0.000010 | 0.000080 |
| R − G | 0.367188 | 0.515137 | **+0.147949** | **[0.137207, 0.159180]** | 0.000010 | 0.000080 |
| R − P | 0.259277 | 0.515137 | **+0.255859** | **[0.242676, 0.269531]** | 0.000010 | 0.000080 |

### Collective emergence ratio

| Contrast | Control mean | Treatment mean | Effect | 95% CI | Raw p | Holm-adjusted p |
|---|---:|---:|---:|---:|---:|---:|
| S − P | 0.259277 | 0.304199 | +0.044922 | [0.033203, 0.055664] | 0.000010 | 0.000080 |
| G − S | 0.304199 | 0.367188 | +0.062988 | [0.052246, 0.074219] | 0.000010 | 0.000080 |
| R − G | 0.367188 | 0.515137 | **+0.147949** | **[0.136719, 0.159668]** | 0.000010 | 0.000080 |
| R − P | 0.259277 | 0.515137 | **+0.255859** | **[0.242676, 0.269043]** | 0.000010 | 0.000080 |

The exact Monte Carlo raw p-value emitted for each test was `9.99990000099999e-06`, the minimum attainable value under the configured `(extreme + 1) / (100000 + 1)` correction when no randomized sign-flip replicate is as extreme as the observed effect. The corresponding eight-test Holm-adjusted value was `7.999920000799993e-05`.

## Preregistered campaign-level decision

The frozen success rule required **both** R − P primary endpoints to satisfy all of the following:

1. effect at least +0.10 absolute;
2. Holm-adjusted p < 0.05; and
3. 95% paired-bootstrap lower bound > 0.

Observed R − P:

- Transfer accuracy: +0.255859; CI lower bound 0.242676; Holm p ≈ 0.000080.
- Collective emergence ratio: +0.255859; CI lower bound 0.242676; Holm p ≈ 0.000080.

Therefore `analysis.campaign_success = true` and, because all quality gates also passed, `scientific_success = true`.

## Quality and mechanism diagnostics

Mean secondary metrics across the 64 confirmatory worlds:

| Metric | Pile | Shared Memory | Provenance Graph | Resonance Field |
|---|---:|---:|---:|---:|
| Evidence coverage | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| Knowledge survival | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| False synthesis | **0.000000** | **0.000000** | **0.000000** | **0.000000** |
| Provenance completeness | 0.000000 | 1.000000 | 1.000000 | 1.000000 |
| Contradiction-resolution F1 | 0.000000 | 0.000000 | 0.000000 | **0.460619** |
| Bridge recall | 0.297145 | 0.358206 | 0.404665 | **0.554174** |
| Duplicate-work rate | 0.077113 | 0.085509 | 0.089070 | 0.097008 |
| Retrieval operation units/query | 10.435547 | 7.531738 | **4.045898** | 4.442383 |

Several mechanisms are visible in the confirmatory data:

- Shared indexing improved transfer while reducing retrieval operation consumption relative to the opaque pile.
- Explicit graph structure improved transfer again and was the most retrieval-efficient arm.
- Resonance dynamics produced the largest capability gain, especially over the static graph (+14.79 percentage points), while using slightly more retrieval operations than G.
- R was the only arm with non-zero contradiction-resolution F1 under the frozen conservative resolver rules.
- R also achieved the highest bridge recall.
- No arm traded accuracy for hallucinated synthesis: false-synthesis remained zero throughout the confirmatory cohort.

These mechanism metrics are secondary and do not determine the preregistered PASS decision.

## Important primary-endpoint dependence

The two nominal primary endpoints were **numerically identical for every arm in every one of the 64 confirmatory worlds**.

This follows from the deterministic benchmark/evaluator geometry: every transfer query is constructed to require evidence from at least two producers, and successful recovery in this implementation also reconstructs the validated path. Consequently, correct transfer answers in the sealed run simultaneously satisfy the collective-emergence criterion.

This does **not** invalidate the preregistered decision rule—the rule was frozen before the confirmatory cohort was opened, and both endpoints pass it. It does, however, reduce the evidential interpretation: the two endpoints should not be described as independent replications of the effect.

The confirmatory result therefore supports one strong statement:

> Under the frozen deterministic relational benchmark, increasing epistemic-substrate structure from an opaque report pile through shared memory and a provenance graph to the Resonance Field produced a large, monotone improvement in persistent post-agent transfer capability while preserving zero false synthesis.

It does **not yet** establish that the Resonance Field creates the same advantage in stochastic LLM populations, live-web research, open-ended tasks, or long-lived societies.

## What this establishes for Resonance Field

Experiments 138–141 provide confirmatory evidence for the causal proposition tested by this campaign: **what the agent population leaves behind materially affects what later evaluators can reconstruct after the producer agents are gone.**

The static graph result shows that relational organization itself contributes beyond flat shared memory. The additional R − G effect shows that, in this benchmark, field dynamics add capability beyond graph structure alone.

The next scientific step should therefore be an **external-validity replication**, not further tuning on this deterministic benchmark. A separate preregistration should replace deterministic producer/evaluator logic with stochastic LLM agents and naturalistic evidence while preserving the P/S/G/R causal isolation and the post-agent transfer test.
