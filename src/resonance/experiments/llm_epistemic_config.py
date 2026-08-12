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
EXPECTED_INSTRUMENTATION_CASE_COUNT = 24
EXPECTED_CONFIRMATORY_CASE_COUNT = 512
EXPECTED_MINIMUM_EVALUABLE_CASE_COUNT = 496
EXPECTED_PROVIDER_NAME = "zai"
EXPECTED_PROVIDER_PROTOCOL = "openai_compatible_chat_completions"
EXPECTED_PROVIDER_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
EXPECTED_REQUESTED_MODEL = "glm-5.1"
EXPECTED_RESPONSE_MODEL = "glm-5.2"
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


@dataclass(frozen=True, slots=True)
class LLMEpistemicConfig:
    name: str
    stage: str
    experiments: tuple[tuple[str, str], ...]
    provider_name: str
    provider_protocol: str
    provider_base_url: str
    requested_model: str
    expected_response_model: str
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
    confirmatory_cases_sealed: bool
    post_seal_case_replacement_allowed: bool
    evaluator_draws: int
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

    def validate(self) -> None:
        if self.name != "llm-epistemic-substrate-142-145-v0.1":
            raise ValueError("campaign name changed")
        if self.stage != "instrumentation_scaffold":
            raise ValueError("campaign stage changed before seal")
        if dict(self.experiments) != EXPECTED_EXPERIMENTS:
            raise ValueError("experiment-to-arm assignment changed")
        provider_identity = (
            self.provider_name,
            self.provider_protocol,
            self.provider_base_url,
            self.requested_model,
            self.expected_response_model,
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
            EXPECTED_PROVIDER_PROBE_RUN_ID,
            EXPECTED_PROVIDER_PROBE_ARTIFACT_ID,
            EXPECTED_PROVIDER_PROBE_ARTIFACT_DIGEST,
            EXPECTED_PROVIDER_PROBE_JSON_SHA256,
            EXPECTED_PROVIDER_REQUEST_CONTRACT_SHA256,
        )
        if provider_identity != expected_provider_identity:
            raise ValueError("provider/model identity freeze changed")
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
        )
        observed_counts = (
            self.instrumentation_case_count,
            self.confirmatory_case_count,
            self.minimum_evaluable_case_count,
        )
        if observed_counts != expected_counts:
            raise ValueError("case cohort/evaluable sizes changed outside the frozen protocol revisions")
        if self.confirmatory_cases_sealed:
            raise ValueError("confirmatory cases must remain unsealed during scaffold stage")
        if self.post_seal_case_replacement_allowed:
            raise ValueError("post-seal confirmatory case replacement must remain disabled")
        if self.evaluator_draws != 5:
            raise ValueError("evaluator draw count changed")
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


def _contrast_tuple(value: object) -> tuple[tuple[str, str], ...]:
    return tuple(tuple(str(x) for x in item) for item in value)  # type: ignore[arg-type]


def load_llm_epistemic_config(path: str | Path) -> LLMEpistemicConfig:
    value = json.loads(Path(path).read_text())
    provider = value["provider"]
    corpus = value["corpus"]
    agents = value["agents"]
    analysis = value["analysis"]
    config = LLMEpistemicConfig(
        name=str(value["name"]),
        stage=str(value["stage"]),
        experiments=tuple((str(k), str(v)) for k, v in value["experiments"].items()),
        provider_name=str(provider["name"]),
        provider_protocol=str(provider["protocol"]),
        provider_base_url=str(provider["base_url"]),
        requested_model=str(provider["requested_model"]),
        expected_response_model=str(provider["expected_response_model"]),
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
        confirmatory_cases_sealed=bool(corpus["confirmatory_cases_sealed"]),
        post_seal_case_replacement_allowed=bool(corpus["post_seal_case_replacement_allowed"]),
        evaluator_draws=int(agents["independent_evaluator_draws_per_case_arm"]),
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
    )
    config.validate()
    return config


__all__ = [
    "EXPECTED_CONFIRMATORY_CASE_COUNT",
    "EXPECTED_INSTRUMENTATION_CASE_COUNT",
    "EXPECTED_MINIMUM_EVALUABLE_CASE_COUNT",
    "EXPECTED_REQUESTED_MODEL",
    "EXPECTED_RESPONSE_MODEL",
    "LLMEpistemicConfig",
    "load_llm_epistemic_config",
]
