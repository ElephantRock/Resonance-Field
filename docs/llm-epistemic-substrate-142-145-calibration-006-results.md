# Experiments 142–145 — PostgreSQL Temporal Calibration 006 Results

Date: 2026-08-12
Status: instrumentation-only; non-inferential; prospectively slot-scored
Case: `instr-postgresql-password-006`
Provider endpoint: Z.AI Coding endpoint (`https://api.z.ai/api/coding/paas/v4`)

## Purpose

Calibration 006 was designed after the Kubernetes temporal case showed that document-level staleness is insufficient when producer normalization does not create an exact competing claim. This case therefore used a versioned PostgreSQL configuration default whose stale and current primary sources literally express different values for the same setting.

Before any arm was permitted to run, the case required:

- at least one event from every assigned producer; and
- at least one cross-producer, cross-time exact `(subject, predicate)` key with differing objects.

The held-out answer used the new ordered-slot semantic scorer.

## Frozen design

Four official `postgres/postgres` sources were pinned before outcome:

1. PostgreSQL 13.0 sample configuration at commit `29be9983a64c011eac0b9ee29895cce71e15ea77`, evidence time `2020-09-21T19:14:05Z`, where `password_encryption` defaults to `md5`;
2. current sample configuration at commit `bdaad789c843f57b1fc66c5ede7abaff8a915c3b`, evidence time `2026-08-12T19:00:00Z`, where `password_encryption` defaults to `scram-sha-256`;
3. current client-authentication documentation at the same current commit; and
4. current `CREATE ROLE` documentation at the same current commit.

The four ordered answer slots were prospectively frozen as:

1. current `password_encryption` default — `scram-sha-256`;
2. current support status of MD5-encrypted passwords — `deprecated`;
3. authentication selected when `pg_hba.conf` says `md5` but the stored password is SCRAM-encrypted — `SCRAM` / equivalent;
4. configuration parameter controlling encryption of a plaintext `CREATE ROLE` password — `password_encryption`.

Three current sources were required evidence; the PostgreSQL 13.0 source was stale contradictory evidence.

Common evaluator controls remained unchanged:

- five draws per arm;
- 12 retrieval-operation units per factual call;
- 24 total retrieval-operation units per answer;
- 8 tool rounds per answer;
- tool-free finalization at either resource boundary.

Frozen plan SHA-256:

`2fb58b8255a80efd02a6d04d142c2f40a1dafad9df75a5cda0d522a1ebd329d1`

Frozen manifest SHA-256:

`00aa656c4e1d705f38f59e9eaaf2c294a39ba0149aa0a01aad6d2fe04330f9fb`

## Execution — SUCCESS

Workflow run: `31634337448`
Trigger/head SHA: `f2733a7490630498ced12af9f27261d5d667c342`
Artifact ID: `9156638366`
Artifact digest: `sha256:05fd7b8aa51aee7b91688f8b698a8b1b48bead018c40c6a5f2464ccd29411777`
Event count: `94`
Event-log SHA-256: `1b1d027da91e86ef72cadeba28829798842eb07cd841f180239deb22131677d9`
Requested model: `glm-5.1`
Observed producer model: `glm-5.2`
Observed evaluator model: `glm-5.2`

The complete canonical event log is present in the artifact. Recomputing SHA-256 over canonical compact JSON reproduces the stored event-log digest exactly.

## Producer and temporal-conflict guards — PASS

All producers deposited evidence:

| Producer | Events |
| --- | ---: |
| current client-auth producer | 26 |
| current default producer | 12 |
| current CREATE ROLE producer | 47 |
| stale PostgreSQL 13 producer | 9 |

The temporal-conflict gate found four exact cross-time differing-object keys. Critically, the intended treatment-relevant collision was present:

- subject: `password_encryption`
- predicate: `default_is`
- stale object: `md5`
- stale time: `2020-09-21T19:14:05Z`
- current object: `scram-sha-256`
- current time: `2026-08-12T19:00:00Z`

The log also contained a second `password_encryption / supports` cross-time collision plus two less scientifically important normalized collisions. Thus this is the first calibration in the campaign where arm evaluation was mechanically conditional on an actual stale/current opposing exact claim key.

## Frozen primary score

| Arm | Correct draws | Accuracy | Mean retrieval units | Draws at 24-unit ceiling | Unsupported synthesis |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pile (P) | 4 / 5 | 0.800 | 17.4 | 1 / 5 | 0.000 |
| Shared Memory (S) | 4 / 5 | 0.800 | 23.6 | 3 / 5 | 0.000 |
| Provenance Graph (G) | 3 / 5 | 0.600 | 5.4 | 0 / 5 | 0.000 |
| Resonance Field (R) | 5 / 5 | 1.000 | 5.8 | 0 / 5 | 0.000 |

Under the prospectively frozen slot scorer, Calibration 006 therefore contains the campaign's first observed **R > G primary split**: `+0.40` on this one instrumentation case.

This remains one case with five nested evaluator draws and is **not inferential evidence** for a population-level R−G effect.

## Primary-score audit: semantic precision, not stale-default selection

The frozen R−G split requires careful interpretation.

Every P/S/G/R draw cited the current `password_encryption / default_is / scram-sha-256` event. No final cited evidence path in any arm cited a stale PostgreSQL 13 event. G therefore did not fail by selecting the stale `md5` default.

The two G failures instead answered the MD5-support-status slot with semantically adjacent current-language variants:

- `supported but will be removed in a future PostgreSQL release`
- `removed in a future PostgreSQL release (still supported)`

Both cited current evidence that support will be removed in a future release. The frozen slot contract required the explicit category `deprecated`, and therefore scored these answers incorrect. A P draw with `removed in a future PostgreSQL release` was likewise scored incorrect.

R, by contrast, used the explicitly `deprecated` current event in all five draws and met the frozen slot contract every time.

Accordingly, the result is a genuine **preregistered semantic-precision difference**, but not a clean demonstration that R alone resolved the stale/current default conflict. The scientific interpretation should distinguish:

1. exact frozen primary accuracy: R 5/5 vs G 3/5; from
2. broader substantive policy understanding: the G near-misses still captured current status/future removal and the correct current default.

No retroactive rescoring is performed.

## Retrieval-efficiency diagnostic

Per-draw retrieval-operation units:

| Draw | P | S | G | R |
| --- | ---: | ---: | ---: | ---: |
| 1 | 24 | 23 | 5 | 5 |
| 2 | 15 | 24 | 6 | 5 |
| 3 | 18 | 24 | 5 | 5 |
| 4 | 15 | 24 | 5 | 9 |
| 5 | 15 | 23 | 6 | 5 |

Mean units:

- P: `17.4`
- S: `23.6`
- G: `5.4`
- R: `5.8`

Both structured graph arms were dramatically more retrieval-efficient than P/S. In this case G was slightly more efficient than R (`5.4` versus `5.8`), reversing the small directional R-efficiency advantage seen in several preceding calibrations. The difference is only `0.4` operation units and is non-inferential.

## Secondary diagnostics

| Arm | Evidence-path F1 | Provenance precision | Provenance recall | Mean Brier |
| --- | ---: | ---: | ---: | ---: |
| P | 1.000 | 1.000 | 1.000 | 0.19668 |
| S | 0.960 | 1.000 | 0.933 | 0.02668 |
| G | 1.000 | 1.000 | 1.000 | 0.36936 |
| R | 1.000 | 1.000 | 1.000 | 0.00092 |

S had one empty answer after consuming the full 24-unit budget; its other four draws met the ordered semantic target.

The high G Brier score reflects high-confidence semantic-status near-misses under the frozen exact slot category, not unsupported or stale evidence. Unsupported synthesis was zero throughout.

## Scientific consequence

Calibration 006 materially improves the campaign's instrumentation quality:

1. the producer-deposit floor passed;
2. the temporal-conflict floor passed with the intended `password_encryption / default_is: md5 → scram-sha-256` collision;
3. ordered slot scoring eliminated the positional ambiguity exposed by Calibration 005;
4. G/R again used far fewer retrieval operations than P/S;
5. the frozen primary endpoint produced the first R > G case-level split; but
6. audit shows the G failures are semantic-precision near-misses on the word `deprecated`, not stale-default errors.

The next replication step should therefore seek **at least one additional independently curated temporal-conflict case** whose primary target is a discrete changed value rather than an open-ended status phrase. Replication of an R > G split on such a case would be much more informative than tuning the current PostgreSQL benchmark.

No Calibration 006 observation is confirmatory evidence and it will not be pooled into confirmatory inference.

## Seal status

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- 96 confirmatory cases remain uncreated/unobserved.
