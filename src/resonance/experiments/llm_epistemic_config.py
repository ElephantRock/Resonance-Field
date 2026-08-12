"""Frozen controls for Experiments 142–145 external-validity replication."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

EXPECTED_EXPERIMENTS = {
    "142": "pile",
    "143": "shared_memory",
    "144": "provenance_graph",
    "145": "resonance_field",
}
EXPECTED_CONTRASTS = (
    ("shared_memory", "pile"),
    ("provenance_graph", "shared_memory"),
    ("resonance_field", "provenance_graph"),
    ("resonance_field", "pile"),
)
EXPECTED_PRIORITY_CONTRASTS = (
    ("resonance_field", "provenance_graph"),
    ("resonance_field", "pile"),
)
EXPECTED_PROTOCOL_REVISION = "004-confirmatory-design-and-seal-freeze"
EXPECTED_PROTOCOL_REVISION_HISTORY = (
    "001-confirmatory-sample-size-512",
    "002-success-rule-and-power-semantics",
    "003-provider-identity-freeze",
    "004-confirmatory-design-and-seal-freeze",
)
EXPECTED_INSTRUMENTATION_CASE_COUNT = 24
EXPECTED_CONFIRMATORY_CASE_COUNT = 512
EXPECTED_MINIMUM_EVALUABLE_CASE_COUNT = 496
EXPECTED_MINIMUM_EVALUABLE_PER_CELL = 15
EXPECTED_CONFIRMATORY_DESIGN_PATH = (
    "configs/experiments/llm-epistemic-substrate-142-145-confirmatory-design.json"
)
EXPECTED_PROVIDER_NAME = "zai"
EXPECTED_PROVIDER_PROTOCOL = "openai_compatible_chat_completions"
EXPECTED_PROVIDER_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
EXPECTED_REQUESTED_MODEL = "glm-5.1"
EXPECTED_RESPONSE_MODEL = "glm-5.2"
EXPECTED_OPENAI_SDK_VERSION = "2.54.0"
EXPECTED_PROVIDER_PROBE_RUN_ID = 31642753502
EXPECTED_PROVIDER_PROBE_ARTIFACT_ID = 9159514128
EXPECTED_PROVIDER_PROBE_ARTIFACT_DIGEST = (
    "sha256:c56a57e94a57657054195960bb0bd556aadd504b7d6d2ba9e53a19babba4757a"
)
EXPECTED_PROVIDER_PROBE_JSON_SHA256 = (
    "835bc51a029517d6d3f5271c5f0f0d98e286df79b486d64742517742c81d7581"
)
EXPECTED_PROVIDER_REQUEST_CONTRACT_SHA256 = (
    "739fba6b309308d0798003f7c1c6a5d9b859b8ad2c4d94fc3bdcd75a8f246acd"
)
EXPECTED_SEAL_SCHEMA_VERSION = "1.0"
EXPECTED_PER_CALL_RETRIEVAL_BUDGET = 12
EXPECTED_TOTAL_RETRIEVAL_BUDGET = 24
EXPECTED_MAXIMUM_RETRIEVAL_TOOL_ROUNDS = 8
EXPECTED_MAXIMUM_UNSUPPORTED_SYNTHESIS_RATE = 0.05
EXPECTED_MINIMUM_EVENT_PROVENANCE_COMPLETENESS = 0.99


@dataclass(frozen=True, slots=True)
class LLMEpistemicConfig:
    name: str
    stage: str
    protocol_revision: str
    protocol_revision_history: tuple[str, ...]
    experiments: tuple[tuple[str, str], ...]
    provider_name: str
    provider_protocol: str
    provider_base_url: str
    requested_model: str
    expected_response_model: str
    provider_openai_sdk_version: str
    provider_probe_run_id: int
    provider_probe_artifact_id: int
    provider_probe_artifact_digest: str
    provider_probe_json_sha256: str
    provider_request_contract_sha256: str
    provider_temperature: float
    provider_thinking_enabled: bool
    provider_clear_thinking: bool
    provider_sdk_internal_retries: int
    provider_transient_retry_business_codes: tuple[str, ...]
    provider_maximum_transient_retries: int
    provider_fail_closed_on_model_mismatch: bool
    instrumentation_case_count: int
    confirmatory_case_count: int
    minimum_evaluable_case_count: int
    minimum_evaluable_per_cell: int
    confirmatory_design_path: str
    confirmatory_cases_sealed: bool
    post_seal_case_replacement_allowed: bool
    evaluator_draws: int
    per_call_retrieval_budget: int
    total_retrieval_budget: int
    maximum_retrieval_tool_rounds: int
    primary_endpoint: str
    planned_contrasts: tuple[tuple[str, str], ...]
    priority_contrasts: tuple[tuple[str, str], ...]
    familywise_alpha: float
    multiple_testing: str
    multiple_testing_family: str
    confidence_interval: float
    bootstrap_resamples: int
    randomization_resamples: int
    minimum_total_effect: float
    minimum_incremental_effect: float
    minimum_effects_are_hard_gates: bool
    success_requires_all_priority_contrasts: bool
    success_requires_holm_significance: bool
    success_requires_positive_ci_lower: bool
    power_detection_target: float
    power_planning_paired_sd_ceiling_r_minus_g: float
    power_reporting: str
    maximum_unsupported_synthesis_rate: float
    minimum_event_provenance_completeness: float
    seal_schema_version: str
    seal_scientific_hashes_required: bool
    seal_source_bytes_reverified: bool
    seal_treatment_execution: bool
    seal_evaluator_execution: bool
    seal_confirmatory_outcomes_observed: bool

    def validate(self) -> None:
        if self.name != "llm-epistemic-substrate-142-145-v0.1":
            raise ValueError("campaign name changed")
        if self.stage != "instrumentation_scaffold":
            raise ValueError("campaign stage changed before seal")
        if self.protocol_revision != EXPECTED_PROTOCOL_REVISION:
            raise ValueError("protocol revision changed")
        if self.protocol_revision_history != EXPECTED_PROTOCOL_REVISION_HISTORY:
            raise ValueError("protocol revision history changed")
        if dict(self.experiments) != EXPECTED_EXPERIMENTS:
            raise ValueError("experiment-to-arm assignment changed")
        provider_identity = (
            self.provider_name,
            self.provider_protocol,
            self.provider_base_url,
            self.requested_model,
            self.expected_response_model,
            self.provider_openai_sdk_version,
            self.provider_probe_run_id,
            self.provider_probe_artifact_id,
            self.provider_probe_artifact_digest,
            self.provider_probe_json_sha256,
            self.provider_request_contract_sha256,
        )
        expected_provider_identity = (
            EXPECTED_PROVIDER_NAME,
            EXPECTED_PROVIDER_PROTOCOL,
            EXPECTED_PROVIDER_BASE_URL,
            EXPECTED_REQUESTED_MODEL,
            EXPECTED_RESPONSE_MODEL,
            EXPECTED_OPENAI_SDK_VERSION,
            EXPECTED_PROVIDER_PROBE_RUN_ID,
            EXPECTED_PROVIDER_PROBE_ARTIFACT_ID,
            EXPECTED_PROVIDER_PROBE_ARTIFACT_DIGEST,
            EXPECTED_PROVIDER_PROBE_JSON_SHA256,
            EXPECTED_PROVIDER_REQUEST_CONTRACT_SHA256,
        )
        if provider_identity != expected_provider_identity:
            raise ValueError("provider/model/SDK identity freeze changed")
        if (
            self.provider_temperature,
            self.provider_thinking_enabled,
            self.provider_clear_thinking,
            self.provider_sdk_internal_retries,
            self.provider_transient_retry_business_codes,
            self.provider_maximum_transient_retries,
            self.provider_fail_closed_on_model_mismatch,
        ) != (1.0, True, False, 0, ("1302", "1305"), 5, True):
            raise ValueError("provider request/retry contract changed")
        expected_counts = (
            EXPECTED_INSTRUMENTATION_CASE_COUNT,
            EXPECTED_CONFIRMATORY_CASE_COUNT,
            EXPECTED_MINIMUM_EVALUABLE_CASE_COUNT,
            EXPECTED_MINIMUM_EVALUABLE_PER_CELL,
        )
        observed_counts = (
            self.instrumentation_case_count,
            self.confirmatory_case_count,
            self.minimum_evaluable_case_count,
            self.minimum_evaluable_per_cell,
        )
        if observed_counts != expected_counts:
            raise ValueError("case cohort/evaluable sizes changed outside the frozen protocol revisions")
        if self.confirmatory_design_path != EXPECTED_CONFIRMATORY_DESIGN_PATH:
            raise ValueError("confirmatory design path changed")
        if self.confirmatory_cases_sealed:
            raise ValueError("confirmatory cases must remain unsealed during scaffold stage")
        if self.post_seal_case_replacement_allowed:
            raise ValueError("post-seal confirmatory case replacement must remain disabled")
        if self.evaluator_draws != 5:
            raise ValueError("evaluator draw count changed")
        if (
            self.per_call_retrieval_budget,
            self.total_retrieval_budget,
            self.maximum_retrieval_tool_rounds,
        ) != (
            EXPECTED_PER_CALL_RETRIEVAL_BUDGET,
            EXPECTED_TOTAL_RETRIEVAL_BUDGET,
            EXPECTED_MAXIMUM_RETRIEVAL_TOOL_ROUNDS,
        ):
            raise ValueError("evaluator retrieval resource controls changed")
        if self.primary_endpoint != "post_agent_task_accuracy":
            raise ValueError("primary endpoint changed")
        if self.planned_contrasts != EXPECTED_CONTRASTS:
            raise ValueError("planned contrasts changed")
        if self.priority_contrasts != EXPECTED_PRIORITY_CONTRASTS:
            raise ValueError("priority contrasts changed")
        if (
            self.familywise_alpha,
            self.multiple_testing,
            self.multiple_testing_family,
            self.confidence_interval,
            self.bootstrap_resamples,
            self.randomization_resamples,
        ) != (
            0.05,
            "holm",
            "all_four_planned_primary_contrasts",
            0.95,
            10_000,
            100_000,
        ):
            raise ValueError("confirmatory inferential controls changed")
        if (self.minimum_total_effect, self.minimum_incremental_effect) != (0.08, 0.03):
            raise ValueError("minimum effect gates changed")
        if not all(
            (
                self.minimum_effects_are_hard_gates,
                self.success_requires_all_priority_contrasts,
                self.success_requires_holm_significance,
                self.success_requires_positive_ci_lower,
            )
        ):
            raise ValueError("campaign success rule changed")
        if (
            self.power_detection_target,
            self.power_planning_paired_sd_ceiling_r_minus_g,
            self.power_reporting,
        ) != (
            0.80,
            0.20,
            "detection_and_hard_gate_pass_probability_separately",
        ):
            raise ValueError("pre-seal power semantics changed")
        if (
            self.maximum_unsupported_synthesis_rate,
            self.minimum_event_provenance_completeness,
        ) != (
            EXPECTED_MAXIMUM_UNSUPPORTED_SYNTHESIS_RATE,
            EXPECTED_MINIMUM_EVENT_PROVENANCE_COMPLETENESS,
        ):
            raise ValueError("confirmatory quality gates changed")
        if self.seal_schema_version != EXPECTED_SEAL_SCHEMA_VERSION:
            raise ValueError("confirmatory seal schema changed")
        if not self.seal_scientific_hashes_required or not self.seal_source_bytes_reverified:
            raise ValueError("confirmatory seal integrity requirements changed")
        if any(
            (
                self.seal_treatment_execution,
                self.seal_evaluator_execution,
                self.seal_confirmatory_outcomes_observed,
            )
        ):
            raise ValueError("confirmatory seal may not execute or observe outcomes")


def _contrast_tuple(value: object) -> tuple[tuple[str, str], ...]:
    return tuple(tuple(str(x) for x in item) for item in value)  # type: ignore[arg-type]


def load_llm_epistemic_config(path: str | Path) -> LLMEpistemicConfig:
    value = json.loads(Path(path).read_text())
    provider = value["provider"]
    corpus = value["corpus"]
    agents = value["agents"]
    analysis = value["analysis"]
    quality = value["quality_gates"]
    seal = value["seal"]
    config = LLMEpistemicConfig(
        name=str(value["name"]),
        stage=str(value["stage"]),
        protocol_revision=str(value["protocol_revision"]),
        protocol_revision_history=tuple(str(item) for item in value["protocol_revision_history"]),
        experiments=tuple((str(k), str(v)) for k, v in value["experiments"].items()),
        provider_name=str(provider["name"]),
        provider_protocol=str(provider["protocol"]),
        provider_base_url=str(provider["base_url"]),
        requested_model=str(provider["requested_model"]),
        expected_response_model=str(provider["expected_response_model"]),
        provider_openai_sdk_version=str(provider["openai_sdk_version"]),
        provider_probe_run_id=int(provider["identity_probe_run_id"]),
        provider_probe_artifact_id=int(provider["identity_probe_artifact_id"]),
        provider_probe_artifact_digest=str(provider["identity_probe_artifact_digest"]),
        provider_probe_json_sha256=str(provider["identity_probe_json_sha256"]),
        provider_request_contract_sha256=str(provider["request_contract_sha256"]),
        provider_temperature=float(provider["temperature"]),
        provider_thinking_enabled=bool(provider["thinking_enabled"]),
        provider_clear_thinking=bool(provider["clear_thinking"]),
        provider_sdk_internal_retries=int(provider["sdk_internal_retries"]),
        provider_transient_retry_business_codes=tuple(
            str(code) for code in provider["transient_retry_business_codes"]
        ),
        provider_maximum_transient_retries=int(provider["maximum_transient_retries"]),
        provider_fail_closed_on_model_mismatch=bool(
            provider["fail_closed_on_response_model_mismatch"]
        ),
        instrumentation_case_count=int(corpus["instrumentation_case_count"]),
        confirmatory_case_count=int(corpus["confirmatory_case_count"]),
        minimum_evaluable_case_count=int(corpus["minimum_evaluable_confirmatory_cases"]),
        minimum_evaluable_per_cell=int(
            corpus["minimum_evaluable_cases_per_domain_challenge_cell"]
        ),
        confirmatory_design_path=str(corpus["confirmatory_design_path"]),
        confirmatory_cases_sealed=bool(corpus["confirmatory_cases_sealed"]),
        post_seal_case_replacement_allowed=bool(corpus["post_seal_case_replacement_allowed"]),
        evaluator_draws=int(agents["independent_evaluator_draws_per_case_arm"]),
        per_call_retrieval_budget=int(agents["per_call_retrieval_operation_budget"]),
        total_retrieval_budget=int(agents["total_retrieval_operation_budget_per_answer"]),
        maximum_retrieval_tool_rounds=int(agents["maximum_retrieval_tool_rounds_per_answer"]),
        primary_endpoint=str(value["primary_endpoint"]),
        planned_contrasts=_contrast_tuple(value["planned_contrasts"]),
        priority_contrasts=_contrast_tuple(value["confirmatory_priority"]),
        familywise_alpha=float(analysis["familywise_alpha"]),
        multiple_testing=str(analysis["multiple_testing"]),
        multiple_testing_family=str(analysis["multiple_testing_family"]),
        confidence_interval=float(analysis["confidence_interval"]),
        bootstrap_resamples=int(analysis["bootstrap_resamples"]),
        randomization_resamples=int(analysis["randomization_resamples"]),
        minimum_total_effect=float(analysis["minimum_total_effect_r_minus_p"]),
        minimum_incremental_effect=float(analysis["minimum_incremental_effect_r_minus_g"]),
        minimum_effects_are_hard_gates=bool(analysis["minimum_effects_are_hard_observed_effect_gates"]),
        success_requires_all_priority_contrasts=bool(
            analysis["campaign_success_requires_all_priority_contrasts"]
        ),
        success_requires_holm_significance=bool(
            analysis["success_requires_holm_adjusted_p_below_alpha"]
        ),
        success_requires_positive_ci_lower=bool(analysis["success_requires_ci_lower_above_zero"]),
        power_detection_target=float(analysis["power_detection_target"]),
        power_planning_paired_sd_ceiling_r_minus_g=float(
            analysis["power_planning_paired_sd_ceiling_r_minus_g"]
        ),
        power_reporting=str(analysis["power_reporting"]),
        maximum_unsupported_synthesis_rate=float(quality["maximum_unsupported_synthesis_rate"]),
        minimum_event_provenance_completeness=float(
            quality["minimum_event_provenance_completeness"]
        ),
        seal_schema_version=str(seal["schema_version"]),
        seal_scientific_hashes_required=bool(seal["scientific_file_sha256_required"]),
        seal_source_bytes_reverified=bool(seal["source_bytes_reverified_at_seal"]),
        seal_treatment_execution=bool(seal["treatment_execution_during_seal"]),
        seal_evaluator_execution=bool(seal["evaluator_execution_during_seal"]),
        seal_confirmatory_outcomes_observed=bool(
            seal["confirmatory_outcomes_observed_during_seal"]
        ),
    )
    config.validate()
    return config


__all__ = [
    "EXPECTED_CONFIRMATORY_CASE_COUNT",
    "EXPECTED_INSTRUMENTATION_CASE_COUNT",
    "EXPECTED_MINIMUM_EVALUABLE_CASE_COUNT",
    "EXPECTED_OPENAI_SDK_VERSION",
    "EXPECTED_PROTOCOL_REVISION",
    "EXPECTED_REQUESTED_MODEL",
    "EXPECTED_RESPONSE_MODEL",
    "LLMEpistemicConfig",
    "load_llm_epistemic_config",
]
