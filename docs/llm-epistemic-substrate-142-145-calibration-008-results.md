# LLM Epistemic Substrate Calibration 008 — PostgreSQL WAL temporal conflict

## Status

Instrumentation-only stochastic calibration completed successfully. This result is non-inferential and does not access or evaluate confirmatory material.

- Workflow run: `31638592754`
- Workflow: `LLM Epistemic Substrate 142-145 PostgreSQL WAL Calibration 008`
- Trigger/head SHA: `3d0b64ce7788582b810068a1ad1c0a5d7d590dac`
- Artifact ID: `9158146739`
- Artifact digest: `sha256:406ae3adb48279eb4c253213ddbe254afbec5dca34f1549aaaced58b5dd7f583`
- Plan SHA-256: `aef6ebfcff4eabbdda19e9b1057fc3cd5c94a48eb4f380a9f239b007cfc3830d`
- Frozen manifest SHA-256: `5e9b52ca0b0d26dac609231073c0142ed3f5f3ff2fcd90b43d20e5b35c7ee4a8`
- Canonical event-log SHA-256: `5cbea37f15fc784523ab227969def4c68a6a7d7665b3cd4a30ffc4cdc9f3ac58`
- Parent substrate-config SHA-256: `9ef9b64aa752a026f9cfe9f29bad49836d5a56eed4e8830138c5f17813ef9520`
- Requested provider/model: `zai` / `glm-5.1`
- Provider-returned producer/evaluator model: `glm-5.2`
- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`

## Frozen case

Case: `instr-postgres-wal-level-008`

The held-out evaluator question required four ordered values:

1. current default `wal_level`;
2. the C constant used to initialize `effective_wal_level`;
3. the minimum `wal_level` needed for continuous archiving;
4. the effective WAL level when configured `wal_level` is `replica` and at least one logical replication slot exists.

Frozen target:

`replica; WAL_LEVEL_REPLICA; replica; logical`

The case used ordered slot-aware semantic scoring, `minimum_events_per_producer: 1`, and `minimum_temporal_conflict_keys: 1`.

## Frozen evidence

Four upstream PostgreSQL sources were pinned before outcome:

| Source | Evidence time | Git commit | Git blob | Frozen SHA-256 |
| --- | --- | --- | --- | --- |
| PostgreSQL 9.5.0 sample `postgresql.conf` | `2016-01-04T21:29:34Z` | `cdd4ed5449bf317cc71b45a8deee0173822e7592` | `18c433b919da6d5b6e002d9bed63e0cff08bd33c` | `88f98975f2f46b13bab4779b550f725666397702e49d778c332dbe0403adffdf` |
| Current sample `postgresql.conf` | `2026-08-12T17:15:48Z` | `bdaad789c843f57b1fc66c5ede7abaff8a915c3b` | `e759f06b50f0670674b2c295624e5d333778045d` | `0132c5cbc2236cf827efcd99c09454a283b2d4bef0515345b70a382b236695d5` |
| Current WAL configuration documentation | `2026-08-12T17:15:48Z` | `bdaad789c843f57b1fc66c5ede7abaff8a915c3b` | `b9b6e6b29fcd0674d773a48b992800316d06d4b1` | `a3e6646fb4bffa46884362fbafdce3c51356b8793c8f9f5d92c40f4af7760b8d` |
| Current GUC implementation | `2026-08-12T17:15:48Z` | `bdaad789c843f57b1fc66c5ede7abaff8a915c3b` | `c6d9b2a6f89ad55211a4ecca432255ea88e10a06` | `855f9f8df53ea74b2e5d6aa4c5e6c46e56677f43f6af1cabff0d166a6d449a0a` |

The stale sample states `wal_level = minimal`; the current sample and current documentation state the default is `replica`. Current implementation evidence contains `static int effective_wal_level = WAL_LEVEL_REPLICA;`. Current documentation also supplies the continuous-archiving and logical-slot answer components.

No single producer received all required current answer evidence.

## Pre-replay temporal gate

All four producers deposited at least one event:

| Producer | Deposited events |
| --- | ---: |
| current GUC code | 9 |
| current sample config | 48 |
| current documentation | 25 |
| stale 9.5 sample config | 42 |

The canonical producer log contains 124 events and passed the exact temporal-conflict gate with **9** cross-producer, cross-time, differing-object `(subject,predicate)` keys.

Most importantly, the intended treatment-relevant collision was present exactly:

`wal_level / default_is: minimal (2016) -> replica (2026)`

The collision comprises the stale sample event plus current sample/documentation events. This is the cleanest calibration so far in which the preregistered stale/current changed value survived stochastic producer normalization as the same exact claim key before substrate replay.

## Primary results

| Arm | Correct | Accuracy | Mean retrieval units |
| --- | ---: | ---: | ---: |
| P — pile | 5/5 | 1.00 | 23.4 |
| S — shared memory | 3/5 | 0.60 | 24.0 |
| G — provenance graph | 5/5 | 1.00 | 8.6 |
| R — resonance field | 5/5 | 1.00 | 7.6 |

Frozen case-level primary contrasts:

- R − G: `0.00`
- R − P: `0.00`
- S − P: `-0.40`
- G − S: `+0.40`

Therefore Calibration 006's case-level R > G primary split did **not** replicate here. The clean temporal-conflict case produces an R/G primary tie.

## Retrieval/resource behavior

Per-draw retrieval units:

- P: `24, 24, 24, 24, 21`
- S: `24, 24, 24, 24, 24`
- G: `9, 8, 8, 8, 10`
- R: `7, 7, 7, 9, 8`

Relative to P, mean retrieval use was approximately:

- G: **63.2% lower**;
- R: **67.5% lower**.

R used approximately **11.6% fewer** mean retrieval-operation units than G in this case. These are instrumentation diagnostics, not inferential efficiency estimates.

S hit the 24-unit hard ceiling in every draw. Two S draws were incorrect: one finalized empty with no citations, and one finalized empty after partial evidence acquisition. The pattern is consistent with the resource-exhaustion mechanism observed in previous harder calibrations.

## Provenance diagnostics

P, G, and R each had provenance precision, provenance recall, and evidence-path F1 of `1.0` in every draw, with unsupported-synthesis rate `0`.

S means were:

- provenance precision: `0.80`;
- provenance recall: `0.7333`;
- evidence-path F1: `0.76`;
- unsupported-synthesis rate: `0`.

All final P/G/R answers cited current required evidence. No final P/G/R answer cited the stale `wal_level = minimal` event.

This supports the narrow observation that all three successful arm families produced the current answer with current cited support. The artifact does **not** retain complete evaluator retrieval traces, so it cannot establish whether stale events were retrieved and explicitly rejected internally. It would therefore be incorrect to attribute R's outcome to a demonstrated recency-rejection path.

## Interpretation

Calibration 008 accomplishes the main instrumentation objective left open by Calibrations 005–007: a real stale/current discrete changed-value conflict was deposited as an exact shared claim key, every intended producer was active, and the case executed through all four arms.

The result does **not** show a primary R > G accuracy effect. P, G, and R all scored 5/5. R was modestly more retrieval-efficient than G, while both structured arms were much more efficient than P/S. S again exhibited hard-budget failure.

Across the two prospectively frozen exact-collision cases with treatment outcomes:

- Calibration 006: R 5/5 vs G 3/5 (`+0.40`), but the proximate difference was semantic-status precision rather than stale-default selection;
- Calibration 008: R 5/5 vs G 5/5 (`0.00`) under a clean exact stale/current changed-value conflict.

Thus there is **no replicated primary R > G treatment effect** in instrumentation. The recurring cross-domain signal is instead retrieval efficiency for G/R and resource fragility for S.

## Scientific boundary

This calibration remains non-inferential. It must not be pooled with confirmatory outcomes, and it does not justify changing the primary endpoint after seeing the result.

The appropriate next campaign step is to stop outcome-driven treatment tuning, freeze the remaining confirmatory protocol/model/scoring/analysis choices, and decide prospectively how much additional instrumentation is needed solely for feasibility and variance estimation before creating and sealing the 96-case confirmatory corpus.
