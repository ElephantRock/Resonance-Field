"""Cryptographic confirmatory seal for Experiments 142–145.

The seal is created only after the complete held-out manifest and frozen source
bytes exist. Building it validates the pre-confirmatory design, re-hashes every
source, and binds the scientific implementation/configuration into one
canonical digest. It does not execute producers, substrates, or evaluators.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .epistemic_substrate_config import load_epistemic_substrate_config
from .llm_epistemic_config import load_llm_epistemic_config
from .llm_epistemic_confirmatory_design import (
    load_confirmatory_design,
    validate_confirmatory_manifest_against_design,
)
from .llm_epistemic_corpus import load_corpus_manifest, verify_source_file

_SEAL_SCHEMA_VERSION = "1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

_FIXED_SCIENTIFIC_PATHS = (
    "pyproject.toml",
    "configs/experiments/epistemic-substrate-138-141.json",
    "configs/experiments/llm-epistemic-substrate-142-145.json",
    "configs/experiments/llm-epistemic-substrate-142-145-confirmatory-design.json",
    "src/resonance/experiments/epistemic_substrate_campaign.py",
    "src/resonance/experiments/epistemic_substrate_config.py",
)
_SCIENTIFIC_GLOBS = (
    "src/resonance/experiments/llm_epistemic_*.py",
    "scripts/*llm_epistemic*.py",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def seal_payload_sha256(payload: dict[str, Any]) -> str:
    return _sha256_bytes(_canonical_bytes(payload))


def collect_scientific_file_hashes(repo_root: str | Path) -> dict[str, str]:
    """Hash all frozen files that can change treatment, scoring, or execution semantics."""

    root = Path(repo_root)
    paths = {root / relative for relative in _FIXED_SCIENTIFIC_PATHS}
    for pattern in _SCIENTIFIC_GLOBS:
        paths.update(path for path in root.glob(pattern) if path.is_file())
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"scientific seal input missing: {sorted(str(path) for path in missing)}")
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(paths, key=lambda item: item.as_posix())
    }


def _validate_source_bytes(manifest: Any, corpus_root: Path) -> None:
    for source in manifest.sources:
        if source.local_path is None:
            raise ValueError(f"confirmatory source {source.source_id} has no frozen local_path")
        verify_source_file(source, corpus_root)


def build_confirmatory_seal(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    corpus_root: str | Path,
    campaign_config_path: str | Path,
    parent_config_path: str | Path,
    design_path: str | Path,
    preseal_code_sha: str,
) -> dict[str, Any]:
    """Validate all pre-seal inputs and return a canonical tamper-evident seal record."""

    code_sha = preseal_code_sha.strip().lower()
    if not _GIT_SHA.fullmatch(code_sha):
        raise ValueError("preseal_code_sha must be a 40-character lowercase Git SHA")

    root = Path(repo_root)
    manifest_file = Path(manifest_path)
    corpus = Path(corpus_root)
    campaign_file = Path(campaign_config_path)
    parent_file = Path(parent_config_path)
    design_file = Path(design_path)

    campaign = load_llm_epistemic_config(campaign_file)
    _parent, parent_config_hash = load_epistemic_substrate_config(parent_file)
    design = load_confirmatory_design(design_file)
    manifest = load_corpus_manifest(manifest_file)
    validate_confirmatory_manifest_against_design(manifest, design)
    _validate_source_bytes(manifest, corpus)

    if campaign.confirmatory_cases_sealed:
        raise ValueError("seal builder expects the pre-seal scaffold, not a previously sealed config")
    if campaign.confirmatory_case_count != design.confirmatory_case_count:
        raise ValueError("campaign and confirmatory design case counts differ")
    if campaign.minimum_evaluable_case_count != design.minimum_evaluable_cases:
        raise ValueError("campaign and confirmatory design evaluable-case floors differ")

    scientific_hashes = collect_scientific_file_hashes(root)
    payload: dict[str, Any] = {
        "schema_version": _SEAL_SCHEMA_VERSION,
        "campaign": campaign.name,
        "preseal_code_sha": code_sha,
        "treatment_execution": False,
        "evaluator_execution": False,
        "confirmatory_outcomes_observed": False,
        "case_count": len(manifest.cases),
        "source_count": len(manifest.sources),
        "minimum_evaluable_case_count": campaign.minimum_evaluable_case_count,
        "minimum_evaluable_per_domain_challenge_cell": design.minimum_evaluable_per_cell,
        "manifest_canonical_sha256": manifest.sha256(),
        "manifest_file_sha256": sha256_file(manifest_file),
        "campaign_config_sha256": sha256_file(campaign_file),
        "parent_config_sha256": parent_config_hash,
        "confirmatory_design_sha256": sha256_file(design_file),
        "provider": {
            "name": campaign.provider_name,
            "protocol": campaign.provider_protocol,
            "base_url": campaign.provider_base_url,
            "requested_model": campaign.requested_model,
            "expected_response_model": campaign.expected_response_model,
            "request_contract_sha256": campaign.provider_request_contract_sha256,
            "identity_probe_run_id": campaign.provider_probe_run_id,
            "identity_probe_artifact_id": campaign.provider_probe_artifact_id,
            "identity_probe_artifact_digest": campaign.provider_probe_artifact_digest,
            "identity_probe_json_sha256": campaign.provider_probe_json_sha256,
        },
        "scientific_file_sha256": scientific_hashes,
    }
    record = {
        "seal_payload": payload,
        "seal_sha256": seal_payload_sha256(payload),
    }
    verify_seal_record(record)
    return record


def verify_seal_record(record: dict[str, Any]) -> None:
    """Verify the internal canonical digest and basic shape of a seal record."""

    if set(record) != {"seal_payload", "seal_sha256"}:
        raise ValueError("confirmatory seal record must contain exactly seal_payload and seal_sha256")
    payload = record["seal_payload"]
    digest = record["seal_sha256"]
    if not isinstance(payload, dict) or not isinstance(digest, str):
        raise ValueError("invalid confirmatory seal record types")
    if payload.get("schema_version") != _SEAL_SCHEMA_VERSION:
        raise ValueError("unsupported confirmatory seal schema")
    if not _SHA256.fullmatch(digest):
        raise ValueError("confirmatory seal digest must be lowercase SHA-256")
    expected = seal_payload_sha256(payload)
    if digest != expected:
        raise ValueError("confirmatory seal digest mismatch")
    code_sha = payload.get("preseal_code_sha")
    if not isinstance(code_sha, str) or not _GIT_SHA.fullmatch(code_sha):
        raise ValueError("confirmatory seal contains invalid preseal_code_sha")
    scientific = payload.get("scientific_file_sha256")
    if not isinstance(scientific, dict) or not scientific:
        raise ValueError("confirmatory seal contains no scientific file hashes")
    for path, value in scientific.items():
        if not isinstance(path, str) or not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError("confirmatory seal contains invalid scientific file hash")
    if payload.get("treatment_execution") is not False:
        raise ValueError("seal creation may not execute treatments")
    if payload.get("evaluator_execution") is not False:
        raise ValueError("seal creation may not execute evaluators")
    if payload.get("confirmatory_outcomes_observed") is not False:
        raise ValueError("seal creation may not observe confirmatory outcomes")


def verify_sealed_scientific_files(record: dict[str, Any], repo_root: str | Path) -> None:
    """Fail closed if any currently checked-out scientific byte differs from the seal."""

    verify_seal_record(record)
    expected = record["seal_payload"]["scientific_file_sha256"]
    observed = collect_scientific_file_hashes(repo_root)
    if observed != expected:
        expected_paths = set(expected)
        observed_paths = set(observed)
        changed = sorted(
            path for path in expected_paths & observed_paths if expected[path] != observed[path]
        )
        added = sorted(observed_paths - expected_paths)
        missing = sorted(expected_paths - observed_paths)
        raise ValueError(
            "sealed scientific files changed: "
            f"changed={changed}; added={added}; missing={missing}"
        )


def load_seal_record(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("confirmatory seal file must contain a JSON object")
    verify_seal_record(value)
    return value


__all__ = [
    "build_confirmatory_seal",
    "collect_scientific_file_hashes",
    "load_seal_record",
    "seal_payload_sha256",
    "sha256_file",
    "verify_seal_record",
    "verify_sealed_scientific_files",
]
