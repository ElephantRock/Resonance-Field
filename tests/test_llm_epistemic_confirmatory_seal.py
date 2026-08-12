from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from resonance.experiments.llm_epistemic_confirmatory_admissibility import (
    validate_evaluable_case_ids,
)
from resonance.experiments.llm_epistemic_confirmatory_design import load_confirmatory_design
from resonance.experiments.llm_epistemic_confirmatory_seal import (
    collect_scientific_file_hashes,
    seal_payload_sha256,
    verify_seal_record,
)

DESIGN_PATH = Path(
    "configs/experiments/llm-epistemic-substrate-142-145-confirmatory-design.json"
)


def _seal_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "campaign": "llm-epistemic-substrate-142-145-v0.1",
        "preseal_code_sha": "a" * 40,
        "treatment_execution": False,
        "evaluator_execution": False,
        "confirmatory_outcomes_observed": False,
        "scientific_file_sha256": {"scientific.py": "b" * 64},
    }


def test_seal_digest_is_deterministic_and_tamper_evident() -> None:
    payload = _seal_payload()
    record = {
        "seal_payload": payload,
        "seal_sha256": seal_payload_sha256(payload),
    }
    verify_seal_record(record)
    assert record["seal_sha256"] == seal_payload_sha256(payload)

    tampered = deepcopy(record)
    tampered["seal_payload"]["campaign"] = "changed"  # type: ignore[index]
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_seal_record(tampered)


def test_scientific_hash_set_includes_provider_analysis_and_sdk_pin() -> None:
    hashes = collect_scientific_file_hashes(".")
    assert "pyproject.toml" in hashes
    assert "src/resonance/experiments/llm_epistemic_zai.py" in hashes
    assert "src/resonance/experiments/llm_epistemic_confirmatory_analysis.py" in hashes
    assert "src/resonance/experiments/llm_epistemic_confirmatory_design.py" in hashes
    assert "src/resonance/experiments/llm_epistemic_confirmatory_seal.py" in hashes


def _case_strata() -> dict[str, tuple[str, str]]:
    design = load_confirmatory_design(DESIGN_PATH)
    result: dict[str, tuple[str, str]] = {}
    for domain_index, domain in enumerate(design.domains):
        for challenge_index, challenge in enumerate(design.challenges):
            for case_index in range(design.cases_per_cell):
                case_id = f"case-{domain_index:02d}-{challenge_index:02d}-{case_index:02d}"
                result[case_id] = (domain, challenge)
    return result


def test_evaluable_gate_accepts_496_when_every_cell_retains_at_least_15() -> None:
    design = load_confirmatory_design(DESIGN_PATH)
    strata = _case_strata()
    removed: set[str] = set()
    for domain_index, domain in enumerate(design.domains[:4]):
        for challenge_index, challenge in enumerate(design.challenges):
            prefix = f"case-{domain_index:02d}-{challenge_index:02d}-"
            case_id = next(case_id for case_id in strata if case_id.startswith(prefix))
            removed.add(case_id)
    assert len(removed) == 16
    evaluable = set(strata) - removed
    status = validate_evaluable_case_ids(strata, evaluable, design)
    assert status.evaluable_case_count == 496
    assert min(count for _domain, _challenge, count in status.cell_counts) == 15


def test_evaluable_gate_rejects_496_when_one_cell_drops_below_15() -> None:
    design = load_confirmatory_design(DESIGN_PATH)
    strata = _case_strata()
    first_cell = (design.domains[0], design.challenges[0])
    removed = {
        case_id
        for case_id, cell in strata.items()
        if cell == first_cell
    }
    removed = set(sorted(removed)[:2])
    for case_id in sorted(strata):
        if len(removed) == 16:
            break
        if case_id not in removed and strata[case_id] != first_cell:
            removed.add(case_id)
    assert len(removed) == 16
    evaluable = set(strata) - removed
    with pytest.raises(ValueError, match="minimum is 15"):
        validate_evaluable_case_ids(strata, evaluable, design)
