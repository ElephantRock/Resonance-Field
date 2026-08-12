# Protocol Revision 004 — Confirmatory Construction, Environment, and Seal Freeze

## Status

Pre-confirmatory and outcome-blind. This revision was made after the instrumentation outcome-tuning stop and before creation, inspection, sealing, or execution of any held-out confirmatory case.

No confirmatory producer, substrate, or evaluator execution is authorized by this revision.

## Why this revision exists

Revisions 001–003 froze the independent-case sample size and success semantics, confirmed power adequacy at 512 planned / 496 minimum evaluable cases, and froze the Z.AI returned-model identity contract. Three remaining degrees of freedom still had to be closed before held-out corpus construction:

1. how the 512 cases are distributed across domains and epistemic challenge types;
2. what source/allocation/scoring constraints make a case admissible; and
3. how the final scientific implementation and corpus bytes are made tamper-evident before execution.

Revision 004 closes those degrees of freedom without observing confirmatory content or outcomes.

## Frozen 8 × 4 × 16 case grid

The confirmatory corpus contains exactly 512 cases: eight domains × four challenge types × sixteen cases per cell.

Domains:

1. programming languages and runtimes;
2. build, package, and dependency tooling;
3. databases and data systems;
4. distributed, cloud, and container systems;
5. networking protocols and internet standards;
6. operating systems and system utilities;
7. scientific computing and data formats; and
8. hardware, compilers, and accelerator toolchains.

Challenge types:

1. **distributed synthesis** — current evidence distributed across at least three independently assigned required sources;
2. **non-stale exact conflict** — at least one exact producer-normalized conflicting claim key, with required evidence constrained to a near-current time span so recency is not the intended resolution mechanism;
3. **temporal update conflict** — at least one exact stale/current conflicting key and a curated required-evidence time gap of at least 180 days; and
4. **high-load distractor synthesis** — exactly eight sources, two per producer, with at least four nonrequired context/distractor sources under the unchanged 24-unit evaluator budget.

The machine-readable design is `configs/experiments/llm-epistemic-substrate-142-145-confirmatory-design.json`; `src/resonance/experiments/llm_epistemic_confirmatory_design.py` rejects deviations from the frozen grid and challenge rules.

## Source and allocation controls

Every case uses exactly four producer agents. Required answer evidence must span at least three producer allocations. Each producer must deposit at least one canonical event before a case may reach substrate replay.

The corpus must contain at least 32 distinct upstream projects and 16 distinct upstream organizations. No upstream project may contribute to more than 16 cases, no upstream organization to more than 32, and the same exact frozen source bytes may not be reused across confirmatory cases.

Every confirmatory source must carry an explicit evidence-state timestamp and upstream diversity metadata. Source SHA-256 values are part of the manifest and are reverified against the frozen local bytes at seal time.

## Frozen scoring convention

All confirmatory multi-value answers use deterministic ordered `required_slots`; no LLM judge determines primary correctness. The challenge-specific answer length is frozen to two through four ordered slots.

Accepted answers and semantic alternatives are frozen before producer execution. Resource-boundary finalization is scored as returned; an outcome-bearing retry may not be used to rescue an answer that exhausted the frozen resource budget. Transport/schema repair may only correct a malformed structured response according to the already frozen provider mechanics.

The primary endpoint remains `post_agent_task_accuracy`. Retrieval efficiency remains secondary.

## Evaluable-case admissibility

The global minimum remains 496 evaluable cases out of 512. Revision 004 adds a local balance gate: every domain × challenge cell must retain at least 15 of its 16 sealed cases.

Arm-independent pre-replay failures remain audit evidence and have no P/S/G/R outcomes. Cases are not replaced after seal. If either the global 496-case floor or any 15/16 cell floor is missed, the confirmatory execution is inadmissible and no campaign PASS/FAIL is reported.

`src/resonance/experiments/llm_epistemic_confirmatory_admissibility.py` implements the cell-local gate.

## Provider environment closure

Provider Revision 003 was probed using OpenAI Python SDK 2.54.0. The optional LLM dependency is now pinned to `openai==2.54.0` so the OpenAI-compatible client implementation cannot silently drift between the identity probe and confirmatory execution.

The already frozen provider contract is unchanged:

- provider: Z.AI;
- request model: `glm-5.1`;
- required returned model: `glm-5.2`;
- temperature: 1.0;
- thinking enabled, `clear_thinking=false`;
- SDK internal retries: 0;
- explicit transient retry business codes: 1302 and 1305, maximum five retries;
- request-contract SHA-256: `739fba6b309308d0798003f7c1c6a5d9b859b8ad2c4d94fc3bdcd75a8f246acd`.

The successful identity probe remains run `31642753502`, artifact `9159514128`, artifact digest `sha256:c56a57e94a57657054195960bb0bd556aadd504b7d6d2ba9e53a19babba4757a`.

## Cryptographic seal procedure

`src/resonance/experiments/llm_epistemic_confirmatory_seal.py` and `scripts/seal_llm_epistemic_confirmatory.py` define the seal operation.

The seal builder must:

1. load and validate the frozen campaign config, parent substrate config, and Revision 004 design;
2. load the complete held-out manifest and verify all 512 cases against the design;
3. re-hash every frozen local source byte against its manifest SHA-256;
4. hash the manifest in both canonical semantic form and raw file form;
5. hash `pyproject.toml`, the parent/config/design files, the validated 138–141 substrate implementation, every `llm_epistemic_*.py` scientific module, and every LLM-epistemic support script;
6. bind the provider identity/probe/request-contract fields and the pre-seal Git SHA; and
7. compute a canonical SHA-256 over the resulting seal payload.

Seal creation explicitly records:

- `treatment_execution: false`;
- `evaluator_execution: false`; and
- `confirmatory_outcomes_observed: false`.

Execution after seal must verify the sealed scientific-file hash mapping before accessing outcome-bearing work. A post-seal scientific file addition, removal, or byte change is a hard failure unless the confirmatory campaign is abandoned and a new preregistered campaign is created.

## Instrumentation boundary update

The instrumentation workflow previously rejected any configuration filename containing `confirmatory`. That rule conflated harmless pre-seal protocol metadata with held-out corpus material.

The workflow now allows the Revision 004 design config but continues to fail closed if the corpus tree contains a confirmatory-named file or any JSON case with `cohort: confirmatory`. Thus design work is testable while held-out case content remains absent and inaccessible.

## Anti-tuning statement

Revision 004 does not change P/S/G/R treatments, evaluator budgets, primary endpoint, planned contrasts, minimum effects, or the post-Calibration-008 scientific interpretation. It does not promote the repeated retrieval-efficiency secondary finding.

No further outcome-bearing instrumentation may be used to alter these rules.

## Next boundary

After Revision 004 is mechanically green, the next phase is **held-out corpus construction under the frozen design**. Construction may populate the 512 sealed candidate cases and source bytes, but no producer/evaluator execution occurs. Only after the complete corpus passes the design validator and the cryptographic seal is created may confirmatory execution be considered.
