# Confirmatory Corpus Curation Procedure — Experiments 142–145

Status: pre-source, pre-seal, no model execution.

Scientific code base: `c33d29a3ad359c040b63c644fb8e552bd28f1615`.

This procedure governs construction of the 512 held-out cases on `experiment/llm-epistemic-confirmatory-corpus`. It does not change the frozen treatment, scoring, provider, resource, analysis, or success-rule code.

## 1. Fixed project allocation

The project allocation is frozen in `project-registry-v1.json` before any held-out source/question selection.

- 32 projects total.
- Four projects per frozen domain.
- 16 cases per project.
- Four cases per challenge type per project.
- Project case allocation is therefore exactly 512 cases.
- The initial registry uses one project per upstream organization, so each organization is planned for 16 cases, below the frozen 32-case organization cap.
- Repository identity/public/non-archived status is recorded separately in `project-registry-verification-v1.json`.

A project may be replaced before seal only for an objective curation-feasibility failure: the repository cannot furnish four admissible cases in each frozen challenge class while respecting source uniqueness, evidence-time, producer-allocation, and source-count rules. Replacement may not be motivated by expected or observed P/S/G/R performance. Any replacement must be in the same domain, use a different upstream project ID, preserve all diversity caps, and be recorded with the exact failed eligibility criterion. No confirmatory producer/evaluator execution may occur before the registry is final.

If a project is replaced after some draft cases were curated, all draft material from the replaced project is discarded from the sealed corpus and its source hashes remain listed in the curation ledger as rejected material; they may not be recycled into another case.

## 2. Candidate ledger before final case selection

Each project receives a candidate ledger before final case files are committed. The ledger records every candidate topic that reaches source-level inspection, including candidates rejected by deterministic eligibility rules.

Required rejection codes:

- `insufficient_unique_sources`
- `insufficient_required_producer_span`
- `no_exact_literal_conflict_target`
- `temporal_gap_below_180_days`
- `nonstale_span_above_30_days`
- `insufficient_distractors`
- `answer_not_deterministically_scorable`
- `answer_requires_more_than_4_slots`
- `answer_requires_fewer_than_2_slots`
- `source_bytes_already_allocated`
- `source_not_primary_or_high_quality_upstream`
- `redistribution_or_snapshot_constraint`
- `other_objective_design_failure`

No rejection code may refer to an arm, expected model behavior, retrieval difficulty inferred from a model, or observed outcome.

## 3. Case-slot naming and deterministic allocation

Case IDs follow the registry rule:

`{domain_code}-{project_code}-{challenge_code}-{01..04}`

Challenge codes:

- `ds` — distributed synthesis
- `nc` — non-stale exact conflict
- `tc` — temporal update conflict
- `hd` — high-load distractor synthesis

Within each project/challenge ledger, eligible candidates are ordered by the tuple:

1. canonical target subject/key string (Unicode code-point order);
2. newest required-source repository path;
3. newest required-source commit timestamp;
4. newest required-source commit SHA.

The first four eligible candidates in that deterministic order fill slots `01` through `04`. Later eligible candidates remain recorded but unselected. This prevents discretionary selection among eligible topics.

## 4. Source freezing

Every selected source is pinned by:

- repository full name;
- immutable commit SHA;
- repository path;
- Git blob SHA when the upstream platform exposes one;
- frozen byte SHA-256;
- canonical URL;
- explicit `evidence_observed_at` representing the evidence state, not the later acquisition time;
- upstream project ID and organization ID.

The exact frozen source bytes may appear in only one confirmatory case. Once a source SHA-256 is allocated, it is unavailable to every other case, even in the same project.

No source may be fetched live during confirmatory evaluation. The final seal re-hashes every local frozen byte.

## 5. Question and scoring freeze

Each case has one held-out question with exactly 2–4 ordered answer slots.

Before any producer execution, curation freezes:

- one canonical semicolon-delimited accepted answer;
- ordered `required_slots`, including only semantically equivalent alternatives;
- optional forbidden contradictory terms when objectively necessary;
- required source IDs;
- producer/source allocation;
- challenge-specific pre-replay gates.

Primary correctness is deterministic. No LLM judge is used to create or score the primary answer. Scoring alternatives may normalize capitalization, spelling variants, aliases, or syntax that are semantically identical; they may not broaden the substantive answer after execution.

## 6. Producer allocation

Every case uses exactly four producers. Required evidence must span at least three producer allocations.

For 4-source cases, each producer receives one source. For 5–6 source cases, additional nonrequired/context sources are distributed without allowing any producer to hold all required evidence. For high-load distractor cases, exactly eight sources are used and each producer receives exactly two.

Every case freezes `minimum_events_per_producer = 1`.

## 7. Challenge-specific source construction

### Distributed synthesis (`ds`)

- 4–6 unique sources.
- At least three required sources.
- Required evidence spans at least three producers.
- No generic or temporal conflict floor.
- The answer requires composition across independently deposited facts rather than a single-source lookup.

### Non-stale exact conflict (`nc`)

- 4–6 unique sources.
- At least three required sources/producers.
- Required-evidence time span no greater than 30 days.
- Sources are curated around the same literal target subject/key with materially conflicting values/claims.
- `minimum_conflict_keys = 1`.
- No temporal conflict floor; recency is not the intended resolution mechanism.

### Temporal update conflict (`tc`)

- 4–6 unique sources.
- At least three required sources/producers.
- The source set includes the same literal target subject/key in stale and current evidence states separated by at least 180 days.
- Required evidence includes the current state.
- `minimum_conflict_keys = 1` and `minimum_temporal_conflict_keys = 1`.
- The question asks for the current value/state, not an open-ended narrative status.

### High-load distractor synthesis (`hd`)

- Exactly eight unique sources.
- Exactly four producers, two sources each.
- 3–4 required sources.
- At least four sources are nonrequired context/distractors.
- No conflict floor is required unless independently mandated by another frozen rule (currently none).
- The 24-operation / 8-round evaluator ceiling is unchanged.

## 8. No difficulty tuning by model execution

During curation:

- no producer agents are run;
- no evaluator agents are run;
- no P/S/G/R substrate outcomes are generated;
- no model is queried to estimate whether a case is easy, hard, or treatment-favorable;
- no completed case is replaced because its expected answer seems too obvious or too difficult to a model.

Curation may use deterministic source inspection and ordinary repository search to establish source facts and design eligibility.

## 9. Completion and seal boundary

The corpus is not eligible for seal until all 512 cases exist and the frozen design validator passes exactly.

Before sealing:

1. every project ledger is complete;
2. all 512 case slots are filled;
3. all source bytes and hashes are present;
4. no source SHA is reused;
5. project/organization caps are satisfied;
6. all ordered scoring contracts are frozen;
7. the 8×4×16 balance is exact.

The seal operation performs validation and hashing only. It performs no treatment/evaluator execution and observes no outcomes.

After seal, case replacement and scientific-code changes are forbidden. Only then may a separate confirmatory execution step be considered.
