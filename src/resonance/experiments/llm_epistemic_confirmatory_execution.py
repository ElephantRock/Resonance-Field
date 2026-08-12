"""Sealed confirmatory execution and aggregation for Experiments 142–145."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .epistemic_substrate_config import EpistemicSubstrateConfig, load_epistemic_substrate_config
from .llm_epistemic_agents import (
    EvaluatorClient,
    EvaluatorTask,
    FrozenSource,
    ProducerClient,
    ProducerTask,
    SubstrateRetrievalTool,
    run_producers,
)
from .llm_epistemic_config import LLMEpistemicConfig, load_llm_epistemic_config
from .llm_epistemic_confirmatory_admissibility import validate_evaluable_case_ids
from .llm_epistemic_confirmatory_analysis import CaseAccuracy, analyze_confirmatory_accuracy
from .llm_epistemic_confirmatory_design import (
    ConfirmatoryDesign,
    load_confirmatory_design,
    validate_confirmatory_manifest_against_design,
)
from .llm_epistemic_confirmatory_seal import (
    load_seal_record,
    sha256_file,
    verify_sealed_scientific_files,
)
from .llm_epistemic_corpus import (
    CorpusManifest,
    ResearchCaseManifest,
    load_corpus_manifest,
    verify_source_file,
)
from .llm_epistemic_instrumentation import (
    ARMS,
    InstrumentationGateError,
    _arm_order,
    _enforce_conflict_floor,
    _enforce_minimum_producer_deposits,
    _enforce_temporal_conflict_floor,
    _event_log_mapping,
    _observed_producer_models,
)
from .llm_epistemic_replay import make_replayed_substrate, replay_event_log
from .llm_epistemic_scoring import score_case


class ConfirmatoryProtocolError(RuntimeError):
    """Hard failure that invalidates confirmatory execution rather than case eligibility."""

    def __init__(self, message: str, *, audit: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.audit = {} if audit is None else audit


def _provider_seal_mapping(campaign: LLMEpistemicConfig) -> dict[str, object]:
    return {
        "name": campaign.provider_name,
        "protocol": campaign.provider_protocol,
        "base_url": campaign.provider_base_url,
        "requested_model": campaign.requested_model,
        "expected_response_model": campaign.expected_response_model,
        "openai_sdk_version": campaign.provider_openai_sdk_version,
        "request_contract_sha256": campaign.provider_request_contract_sha256,
        "identity_probe_run_id": campaign.provider_probe_run_id,
        "identity_probe_artifact_id": campaign.provider_probe_artifact_id,
        "identity_probe_artifact_digest": campaign.provider_probe_artifact_digest,
        "identity_probe_json_sha256": campaign.provider_probe_json_sha256,
    }


def load_sealed_confirmatory_inputs(
    *,
    seal_path: str | Path,
    repo_root: str | Path,
    manifest_path: str | Path,
    campaign_config_path: str | Path,
    parent_config_path: str | Path,
    design_path: str | Path,
) -> tuple[
    dict[str, Any],
    CorpusManifest,
    LLMEpistemicConfig,
    EpistemicSubstrateConfig,
    ConfirmatoryDesign,
]:
    """Verify the seal before parsing held-out case content or allowing execution."""

    seal = load_seal_record(seal_path)
    verify_sealed_scientific_files(seal, repo_root)
    payload = seal["seal_payload"]

    manifest_file = Path(manifest_path)
    campaign_file = Path(campaign_config_path)
    design_file = Path(design_path)
    if sha256_file(manifest_file) != payload.get("manifest_file_sha256"):
        raise ConfirmatoryProtocolError("sealed manifest file hash mismatch")
    if sha256_file(campaign_file) != payload.get("campaign_config_sha256"):
        raise ConfirmatoryProtocolError("sealed campaign config hash mismatch")
    if sha256_file(design_file) != payload.get("confirmatory_design_sha256"):
        raise ConfirmatoryProtocolError("sealed confirmatory design hash mismatch")

    campaign = load_llm_epistemic_config(campaign_file)
    design = load_confirmatory_design(design_file)
    parent, parent_hash = load_epistemic_substrate_config(parent_config_path)
    if parent_hash != payload.get("parent_config_sha256"):
        raise ConfirmatoryProtocolError("sealed parent substrate config hash mismatch")
    if payload.get("provider") != _provider_seal_mapping(campaign):
        raise ConfirmatoryProtocolError("sealed provider identity/request contract mismatch")

    manifest = load_corpus_manifest(manifest_file)
    validate_confirmatory_manifest_against_design(manifest, design)
    if manifest.sha256() != payload.get("manifest_canonical_sha256"):
        raise ConfirmatoryProtocolError("sealed canonical manifest hash mismatch")
    if len(manifest.cases) != payload.get("case_count"):
        raise ConfirmatoryProtocolError("sealed case count mismatch")
    if len(manifest.sources) != payload.get("source_count"):
        raise ConfirmatoryProtocolError("sealed source count mismatch")
    if payload.get("minimum_evaluable_case_count") != campaign.minimum_evaluable_case_count:
        raise ConfirmatoryProtocolError("sealed global evaluable-case floor mismatch")
    if payload.get("minimum_evaluable_per_domain_challenge_cell") != design.minimum_evaluable_per_cell:
        raise ConfirmatoryProtocolError("sealed cell evaluability floor mismatch")
    return seal, manifest, campaign, parent, design


def _case_frozen_sources(
    case: ResearchCaseManifest,
    manifest: CorpusManifest,
    corpus_root: str | Path,
) -> dict[str, FrozenSource]:
    by_id = {source.source_id: source for source in manifest.sources}
    root = Path(corpus_root)
    frozen: dict[str, FrozenSource] = {}
    for source_id in case.source_ids:
        source = by_id[source_id]
        if source.local_path is None:
            raise ConfirmatoryProtocolError(f"confirmatory source {source_id} has no frozen local path")
        verify_source_file(source, root)
        frozen[source_id] = FrozenSource(
            source_id=source.source_id,
            sha256=source.sha256,
            text=(root / source.local_path).read_text(),
            observed_at=source.controlled_evidence_time,
        )
    return frozen


def _producer_tasks(
    case: ResearchCaseManifest,
    sources: dict[str, FrozenSource],
) -> tuple[ProducerTask, ...]:
    return tuple(
        ProducerTask(
            case_id=case.case_id,
            producer_id=producer_id,
            sources=tuple(sources[source_id] for source_id in source_ids),
            research_goal=case.question,
        )
        for producer_id, source_ids in case.producer_source_allocations
    )


def _assert_producer_identity(event_log: Any, campaign: LLMEpistemicConfig) -> None:
    for event in event_log.events:
        metadata = event.metadata
        observed = (
            metadata.get("provider"),
            metadata.get("requested_model"),
            metadata.get("response_model"),
            metadata.get("base_url"),
        )
        expected = (
            campaign.provider_name,
            campaign.requested_model,
            campaign.expected_response_model,
            campaign.provider_base_url,
        )
        if observed != expected:
            raise ConfirmatoryProtocolError(
                "producer provider/model identity drifted after seal",
                audit={
                    "event_id": event.event_id,
                    "observed_provider_identity": list(observed),
                    "expected_provider_identity": list(expected),
                },
            )


def _normalize_gate_failure(
    exc: InstrumentationGateError,
    case: ResearchCaseManifest,
    seal_sha256: str,
) -> dict[str, Any]:
    audit = dict(exc.audit)
    audit.update(
        {
            "status": "pre_replay_gate_failure",
            "cohort": "confirmatory",
            "inferential": False,
            "confirmatory_access": True,
            "confirmatory_cases_evaluated": False,
            "outcome_bearing_treatment_execution": False,
            "seal_sha256": seal_sha256,
            "domain_id": case.domain_id,
            "challenge_type": case.challenge_type,
        }
    )
    return audit


def run_confirmatory_case(
    *,
    case: ResearchCaseManifest,
    manifest: CorpusManifest,
    corpus_root: str | Path,
    campaign: LLMEpistemicConfig,
    substrate_config: EpistemicSubstrateConfig,
    producer_client: ProducerClient,
    evaluator_client: EvaluatorClient,
    seal_sha256: str,
) -> dict[str, Any]:
    """Run one sealed case; only arm-independent pre-replay gates may make it unevaluable."""

    if case.cohort != "confirmatory":
        raise ConfirmatoryProtocolError("confirmatory runner received a non-confirmatory case")
    sources = _case_frozen_sources(case, manifest, corpus_root)
    event_log = run_producers(_producer_tasks(case, sources), producer_client)
    _assert_producer_identity(event_log, campaign)

    try:
        producer_counts = _enforce_minimum_producer_deposits(case, event_log)
        conflict_keys = _enforce_conflict_floor(case, event_log, producer_counts)
        temporal_conflict_keys = _enforce_temporal_conflict_floor(
            case,
            event_log,
            producer_counts,
            conflict_keys,
        )
    except InstrumentationGateError as exc:
        return _normalize_gate_failure(exc, case, seal_sha256)

    evidence = replay_event_log(event_log, substrate_config)
    event_log_sha256 = event_log.sha256()
    draws: list[dict[str, Any]] = []
    evaluator_models: set[str] = set()
    try:
        for draw_id in range(1, campaign.evaluator_draws + 1):
            order = _arm_order(case.case_id, draw_id)
            arms: dict[str, Any] = {}
            for arm in order:
                substrate = make_replayed_substrate(arm, evidence, substrate_config)
                tool = SubstrateRetrievalTool(
                    event_log,
                    evidence,
                    substrate,
                    total_budget=campaign.total_retrieval_budget,
                )
                answer = evaluator_client.evaluate(
                    EvaluatorTask(
                        case_id=case.case_id,
                        question_id=case.held_out_question_id,
                        question=case.question,
                        draw_id=draw_id,
                    ),
                    tool,
                )
                if answer.model != campaign.expected_response_model:
                    raise ConfirmatoryProtocolError(
                        "evaluator provider-returned model identity mismatch",
                        audit={
                            "case_id": case.case_id,
                            "draw_id": draw_id,
                            "arm": arm,
                            "expected_response_model": campaign.expected_response_model,
                            "observed_response_model": answer.model,
                        },
                    )
                if not 0 <= answer.retrieval_operation_units <= campaign.total_retrieval_budget:
                    raise ConfirmatoryProtocolError(
                        "evaluator exceeded sealed retrieval-operation budget",
                        audit={
                            "case_id": case.case_id,
                            "draw_id": draw_id,
                            "arm": arm,
                            "retrieval_operation_units": answer.retrieval_operation_units,
                        },
                    )
                evaluator_models.add(answer.model)
                arms[arm] = {
                    "answer": asdict(answer),
                    "score": asdict(score_case(case, answer, event_log)),
                    "event_log_sha256": event_log_sha256,
                }
            draws.append({"draw_id": draw_id, "arm_order": list(order), "arms": arms})
    except ConfirmatoryProtocolError:
        raise
    except Exception as exc:
        raise ConfirmatoryProtocolError(
            "post-replay evaluator/provider failure invalidates confirmatory execution",
            audit={
                "case_id": case.case_id,
                "completed_draw_count": len(draws),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        ) from exc

    return {
        "status": "evaluable",
        "case_id": case.case_id,
        "cohort": "confirmatory",
        "inferential": True,
        "confirmatory_access": True,
        "confirmatory_cases_evaluated": True,
        "seal_sha256": seal_sha256,
        "domain_id": case.domain_id,
        "challenge_type": case.challenge_type,
        "event_log_sha256": event_log_sha256,
        "event_count": len(event_log.events),
        "event_log": _event_log_mapping(event_log),
        "producer_ids": list(event_log.producer_ids()),
        "producer_event_counts": producer_counts,
        "conflict_key_count": len(conflict_keys),
        "conflict_keys": list(conflict_keys),
        "temporal_conflict_key_count": len(temporal_conflict_keys),
        "temporal_conflict_keys": list(temporal_conflict_keys),
        "observed_producer_models": _observed_producer_models(event_log),
        "observed_evaluator_models": sorted(evaluator_models),
        "draws": draws,
    }


def _case_accuracy(result: dict[str, Any]) -> CaseAccuracy:
    arm_draws: dict[str, tuple[float, ...]] = {}
    for arm in ARMS:
        values = tuple(float(draw["arms"][arm]["score"]["correct"]) for draw in result["draws"])
        arm_draws[arm] = values
    return CaseAccuracy(case_id=str(result["case_id"]), arm_draws=arm_draws)


def _quality_diagnostics(
    manifest: CorpusManifest,
    evaluable_results: tuple[dict[str, Any], ...],
    campaign: LLMEpistemicConfig,
) -> dict[str, Any]:
    source_hashes = {source.source_id: source.sha256.lower() for source in manifest.sources}
    provenance_total = 0
    provenance_complete = 0
    unsupported_total = 0.0
    score_total = 0
    identical_hashes = True

    for result in evaluable_results:
        expected_hash = result["event_log_sha256"]
        for event in result["event_log"]["events"]:
            provenance_total += 1
            if source_hashes.get(event["source_id"]) == str(event["source_sha256"]).lower():
                provenance_complete += 1
        for draw in result["draws"]:
            for arm in ARMS:
                arm_result = draw["arms"][arm]
                if arm_result["event_log_sha256"] != expected_hash:
                    identical_hashes = False
                score = arm_result["score"]
                unsupported_total += float(score["unsupported_synthesis"])
                score_total += 1

    provenance_rate = provenance_complete / provenance_total if provenance_total else 0.0
    unsupported_rate = unsupported_total / score_total if score_total else 1.0
    passes = (
        identical_hashes
        and provenance_rate >= campaign.minimum_event_provenance_completeness
        and unsupported_rate <= campaign.maximum_unsupported_synthesis_rate
    )
    return {
        "identical_event_log_across_arms": identical_hashes,
        "event_provenance_completeness": provenance_rate,
        "minimum_event_provenance_completeness": campaign.minimum_event_provenance_completeness,
        "unsupported_synthesis_rate": unsupported_rate,
        "maximum_unsupported_synthesis_rate": campaign.maximum_unsupported_synthesis_rate,
        "passes": passes,
    }


def aggregate_confirmatory_results(
    *,
    results: Iterable[dict[str, Any]],
    manifest: CorpusManifest,
    campaign: LLMEpistemicConfig,
    design: ConfirmatoryDesign,
    seal_sha256: str,
) -> dict[str, Any]:
    """Aggregate exactly one sealed result per case and analyze only an admissible cohort."""

    result_values = tuple(results)
    case_ids = [str(result.get("case_id", "")) for result in result_values]
    if len(case_ids) != len(set(case_ids)):
        raise ConfirmatoryProtocolError("duplicate confirmatory case result detected; rerun selection forbidden")

    expected_cases = {case.case_id: case for case in manifest.cases}
    observed_ids = set(case_ids)
    missing = sorted(set(expected_cases) - observed_ids)
    extra = sorted(observed_ids - set(expected_cases))
    if missing or extra:
        return {
            "campaign": campaign.name,
            "cohort": "confirmatory",
            "seal_sha256": seal_sha256,
            "campaign_admissible": False,
            "campaign_success": None,
            "analysis": None,
            "reason": "incomplete_or_unrecognized_case_results",
            "missing_case_ids": missing,
            "extra_case_ids": extra,
        }

    invalid_results = [
        result
        for result in result_values
        if result.get("status") not in {"evaluable", "pre_replay_gate_failure"}
        or result.get("seal_sha256") != seal_sha256
    ]
    if invalid_results:
        return {
            "campaign": campaign.name,
            "cohort": "confirmatory",
            "seal_sha256": seal_sha256,
            "campaign_admissible": False,
            "campaign_success": None,
            "analysis": None,
            "reason": "mechanical_protocol_or_seal_failure_present",
            "invalid_case_ids": sorted(str(result.get("case_id", "")) for result in invalid_results),
        }

    evaluable = tuple(result for result in result_values if result["status"] == "evaluable")
    evaluable_ids = {str(result["case_id"]) for result in evaluable}
    case_strata = {
        case.case_id: (str(case.domain_id), str(case.challenge_type)) for case in manifest.cases
    }
    try:
        evaluability = validate_evaluable_case_ids(case_strata, evaluable_ids, design)
    except ValueError as exc:
        return {
            "campaign": campaign.name,
            "cohort": "confirmatory",
            "seal_sha256": seal_sha256,
            "campaign_admissible": False,
            "campaign_success": None,
            "analysis": None,
            "reason": "evaluable_case_floor_failed",
            "error": str(exc),
            "evaluable_case_count": len(evaluable_ids),
        }

    quality = _quality_diagnostics(manifest, evaluable, campaign)
    if not quality["passes"]:
        return {
            "campaign": campaign.name,
            "cohort": "confirmatory",
            "seal_sha256": seal_sha256,
            "campaign_admissible": False,
            "campaign_success": None,
            "analysis": None,
            "reason": "confirmatory_quality_gate_failed",
            "evaluable_case_count": len(evaluable_ids),
            "evaluability": asdict(evaluability),
            "quality_gates": quality,
        }

    minimum_effects = {
        ("resonance_field", "provenance_graph"): campaign.minimum_incremental_effect,
        ("resonance_field", "pile"): campaign.minimum_total_effect,
    }
    analysis = analyze_confirmatory_accuracy(
        (_case_accuracy(result) for result in evaluable),
        contrasts=campaign.planned_contrasts,
        minimum_effects=minimum_effects,
        familywise_alpha=campaign.familywise_alpha,
        confidence=campaign.confidence_interval,
        bootstrap_resamples=campaign.bootstrap_resamples,
        randomization_resamples=campaign.randomization_resamples,
    )
    return {
        "campaign": campaign.name,
        "cohort": "confirmatory",
        "seal_sha256": seal_sha256,
        "campaign_admissible": True,
        "campaign_success": analysis.campaign_success,
        "evaluable_case_count": len(evaluable_ids),
        "pre_replay_gate_failure_count": len(result_values) - len(evaluable_ids),
        "evaluability": asdict(evaluability),
        "quality_gates": quality,
        "analysis": asdict(analysis),
    }


__all__ = [
    "ConfirmatoryProtocolError",
    "aggregate_confirmatory_results",
    "load_sealed_confirmatory_inputs",
    "run_confirmatory_case",
]
