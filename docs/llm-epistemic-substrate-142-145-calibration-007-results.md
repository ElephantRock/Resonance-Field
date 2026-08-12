# LLM Epistemic Substrate Calibration 007 — OpenJDK temporal gate abort

## Status

Instrumentation-only gate abort. No P/S/G/R substrate replay occurred and no evaluator draws were executed.

- Workflow run: `31636162375`
- Trigger/head SHA: `e8da2bfd295013e49f67667bf5e01def914d1cbf`
- Workflow: `LLM Epistemic Substrate 142-145 OpenJDK Calibration 007`
- Plan SHA-256: `377e285ddba9309207fbd4403cedda0f324c9245c5229f5b0c097a1e8e58203c`
- Frozen manifest SHA-256: `88dc77543084041ca3ca03f2ddb93d910e33c64b675e003a748170ac65d5b220`
- Confirmatory access: false
- Inferential status: false

## Frozen case

Case `instr-openjdk-keystore-007` used four pinned OpenJDK sources:

1. OpenJDK 8 GA Linux security properties, observed `2014-03-18T18:55:18Z`;
2. current OpenJDK security properties, observed `2026-08-12T16:49:58Z`;
3. current `KeyStore` API implementation documentation;
4. current `keytool` manual.

The ordered primary target was:

`pkcs12; true; keystore.type; .keystore`

The case required at least one event from every assigned producer and at least one cross-producer, cross-time exact `(subject,predicate)` key with differing objects before replay.

## What happened

All implementation, confirmatory-boundary, source-freeze, semantic-contract, timestamp, and credential gates passed. Producer execution then completed far enough to pass the minimum producer-deposit check. The next pre-replay gate rejected the canonical producer log:

`temporal conflict-key floor not met before substrate replay: minimum=1; observed=0`

The exception was raised before `replay_event_log(...)`. Therefore:

- no arm substrate was constructed from the producer log;
- no evaluator was called;
- no treatment score exists;
- no R−G or R−P contrast exists;
- the run must not be interpreted as a null result.

The workflow did not upload a result artifact after the gate exception, so the exact rejected producer event log was not retained. The run log does retain the frozen source and manifest hashes and the explicit `observed=0` gate decision.

## Interpretation

Calibration 007 is evidence about instrumentation feasibility, not arm performance. The OpenJDK source package contained a real historical/current keystore-default change, but stochastic producer normalization did not express that change as an exact shared claim key under the preregistered collision definition.

The collision floor is retained unchanged. We do not weaken the gate, reinterpret near-matches, or run evaluators on a non-colliding log.

## Next design requirement

The next temporal calibration should use an upstream project where the stale and current sources expose the same literal configuration keyword and a discrete changed value in closely matched source forms. A suitable candidate is OpenSSH `PermitRootLogin`, whose shipped sample configuration changed from `yes` in OpenSSH 6.6p1 to `prohibit-password` in current OpenSSH.

A prospective observability improvement is also warranted: pre-replay gate failures should retain the canonical producer log and gate diagnostics without changing successful-run treatment behavior.
