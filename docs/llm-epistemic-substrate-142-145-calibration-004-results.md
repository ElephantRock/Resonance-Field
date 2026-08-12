# Experiments 142–145 — Go Calibration 004 Results

Date: 2026-08-12
Status: instrumentation-only; non-inferential; prospectively semantic-scored
Case: `instr-go-toolchain-004`
Provider endpoint: Z.AI Coding endpoint (`https://api.z.ai/api/coding/paas/v4`)

## Frozen design

Calibration 004 moved the same resource-constrained design into the Go ecosystem and was the first case scored prospectively with the deterministic semantic-answer contract introduced after Calibration 003 exposed whole-string punctuation confounding.

Before any Calibration 004 outcome existed, the project froze:

- four commit-pinned `golang/go` sources at commit `4b6ec2e0c834dbf7cdf880da379bdd65737eae6a`;
- one source per producer;
- three required evidence sources distributed across three producers;
- one adjacent GODEBUG document intended as a fourth-source distractor;
- five evaluator draws per P/S/G/R arm;
- 12 retrieval-operation units per call;
- 24 total retrieval-operation units per evaluator answer; and
- an 8-tool-round ceiling per evaluator answer.

The held-out task asks for four semantic target terms: the shipped `GOTOOLCHAIN=auto` assignment, the only two valid minimum-toolchain suffixes (`+auto` and `+path`), and `toolchaintrace=1` as the GODEBUG control. `GOTOOLCHAIN=local` is preregistered as a forbidden contradictory term.

Frozen plan SHA-256:

`93cc5fbc7448ee8ec8e5d7720a5ced7668e87f5431b9412c45ac4ca33e8c8f23`

Frozen manifest SHA-256:

`bd4292a62aa24bd5491d1e8e8f92dc5af41ccf5e3e2b3455cf59307744ae3e61`

## Execution chronology

### v1 — round-ceiling control-flow failure, no accepted result

Workflow run `31623022754` passed implementation, confirmatory-seal, source-freeze, semantic-scoring-contract, and credential checks. During the live evaluator phase an evaluator reached the frozen 8-tool-round ceiling before exhausting its 24 retrieval-operation units. The then-current control path raised `RuntimeError: evaluator exceeded maximum retrieval rounds`, so the workflow produced no result artifact and no accepted arm score.

The repair was mechanical: reaching either the 24-operation ceiling or the 8-tool-round ceiling now disables tools and forces a final structured answer from evidence already retrieved. Neither ceiling was increased. A regression test verifies that no ninth tool round occurs and that unused retrieval budget is not spent merely to force finalization.

Ordinary CI on Python 3.12 and 3.13 plus the dedicated instrumentation contract passed before v2 was triggered.

### v2 — SUCCESS

Workflow run: `31624101126`
Head SHA: `e57cfd272b2659dbd5a65a5dd67c9c26f287cae1`
Artifact ID: `9152940357`
Artifact digest: `sha256:75be4ac2aba6da398e4d91cecdeb3b151f5e47a891bc613b0ac72f6d510979c2`
Event count: `51`
Event-log SHA-256: `7d34afc3adf74ffe34c7e4b61ffe6520b1c0a365949cb9396fb0e27b3d9aadc3`
Requested model: `glm-5.1`
Observed producer model: `glm-5.2`
Observed evaluator model: `glm-5.2`

The artifact contains the complete canonical event log. Recomputing SHA-256 over canonical JSON (`sort_keys=True`, compact separators) reproduces the stored event-log digest exactly.

## Primary semantic score

| Arm | Correct draws | Mean accuracy | Mean retrieval units | Draws at 24-unit ceiling | Unsupported synthesis |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pile (P) | 5 / 5 | 1.000 | 20.4 | 1 / 5 | 0.000 |
| Shared Memory (S) | 5 / 5 | 1.000 | 18.6 | 0 / 5 | 0.000 |
| Provenance Graph (G) | 5 / 5 | 1.000 | 7.8 | 0 / 5 | 0.000 |
| Resonance Field (R) | 5 / 5 | 1.000 | 7.0 | 0 / 5 | 0.000 |

Calibration 004 is therefore ceiling-saturated on the primary endpoint and supplies **no case-level primary accuracy estimate for R − G or R − P**.

The semantic scorer behaved as intended: punctuation variants such as comma versus `and`, and the provider's occasional `#toolchaintrace=1` rendering, were accepted because every required semantic group was present and the forbidden term was absent.

## Retrieval-efficiency diagnostic

Under the same 24-unit total ceiling:

- R used 65.7% fewer mean retrieval units than P (`7.0` versus `20.4`);
- R used 62.4% fewer than S (`7.0` versus `18.6`);
- R used 10.3% fewer than G (`7.0` versus `7.8`);
- G used 61.8% fewer than P and 58.1% fewer than S.

Per-draw retrieval units were:

| Draw | P | S | G | R |
| --- | ---: | ---: | ---: | ---: |
| 1 | 21 | 22 | 8 | 6 |
| 2 | 15 | 14 | 9 | 6 |
| 3 | 24 | 22 | 6 | 5 |
| 4 | 21 | 12 | 7 | 7 |
| 5 | 21 | 23 | 9 | 11 |

This is a secondary instrumentation observation only. With five nested evaluator draws on one case, the small G–R difference must not be interpreted inferentially.

## Secondary diagnostics

| Arm | Evidence-path F1 | Provenance precision | Provenance recall | Brier | Mean input tokens | Mean output tokens | Mean latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P | 1.000 | 1.000 | 1.000 | 0.01348 | 16131.4 | 2856.6 | 42587.4 |
| S | 0.920 | 1.000 | 0.867 | 0.00450 | 14553.4 | 1435.4 | 29757.0 |
| G | 1.000 | 1.000 | 1.000 | 0.01138 | 19356.4 | 2982.0 | 66725.4 |
| R | 1.000 | 1.000 | 1.000 | 0.00268 | 17476.0 | 1947.6 | 32236.0 |

S draws 1 and 5 cited only two of the three preregistered required sources, producing provenance recall `2/3` and evidence-path F1 `0.8` despite semantically correct answers. The current unsupported-synthesis metric remains zero because those answers had valid deposited support; this distinction should be retained when interpreting provenance completeness.

## Distractor-deposition limitation

The fourth assigned producer received `doc/godebug.md` as an adjacent distractor source, but emitted zero ontology-valid epistemic events. The canonical event log therefore contains events from only producers 1–3:

- producer 1 / `go.env`: 7 events;
- producer 2 / toolchain-selection implementation: 24 events;
- producer 3 / toolchain-trace test: 20 events;
- producer 4 / general GODEBUG documentation: 0 events.

Thus Calibration 004 preserves three-producer distributed required evidence but **does not test active fourth-source distractor competition after deposition**. Future calibration cases should add a pre-execution instrumentation guard requiring a minimum nonzero event deposit from every assigned producer when the case design depends on an active distractor.

## Model-identity audit

The workflow requested `glm-5.1`, while every observed producer and evaluator completion reported `glm-5.2`. This mismatch is preserved in event metadata and the result artifact. It is acceptable for instrumentation discovery but must be resolved into an explicit provider-returned identity policy before confirmatory sealing.

## Scientific consequence

Calibration 004 strengthens the repeated **retrieval-efficiency** pattern but not the primary accuracy claim:

1. semantic scoring removes the punctuation artifact exposed by Calibration 003;
2. G/R again recover the required evidence with far fewer retrieval-operation units than P/S;
3. R is directionally more retrieval-efficient than G on this case, but only by 0.8 mean units and with no accuracy difference;
4. the primary endpoint remains too easy on this Go case; and
5. the intended distractor failed to deposit, so the next calibration tranche should explicitly guarantee active contradictory/distractor events rather than relying only on source assignment.

No Calibration 004 observation is confirmatory evidence and it will not be pooled into confirmatory inference.

## Seal status

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- 96 confirmatory cases remain uncreated/unobserved.
