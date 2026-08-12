"""Run the sealed confirmatory cohort for Epistemic Substrate Experiments 138–141."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .epistemic_substrate_analysis import analyze_confirmatory
from .epistemic_substrate_campaign import ArmMetrics, run_world
from .epistemic_substrate_config import EpistemicSubstrateConfig, load_epistemic_substrate_config

CONFIRMATORY_SEAL = "OPEN-138-141-CONFIRMATORY"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--instrumentation-evidence", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--confirmatory-seal", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    return parser


def _validate_instrumentation_evidence(
    path: str | Path,
    config: EpistemicSubstrateConfig,
    config_hash: str,
) -> None:
    value = json.loads(Path(path).read_text())
    if value.get("campaign") != config.name:
        raise ValueError("instrumentation evidence campaign does not match")
    if value.get("config_hash") != config_hash:
        raise ValueError("instrumentation evidence config hash does not match")
    if value.get("inferential") is not False:
        raise ValueError("instrumentation evidence must be non-inferential")
    if value.get("confirmatory_seeds_evaluated") is not False:
        raise ValueError("instrumentation evidence already touched confirmatory seeds")
    if value.get("instrumentation_validated") is not True:
        raise ValueError("instrumentation evidence did not pass hard gates")
    if tuple(value.get("seeds", ())) != config.instrumentation_seeds:
        raise ValueError("instrumentation evidence seed cohort does not match")


def _quality_gates(
    paired_worlds: dict[int, tuple[ArmMetrics, ...]],
    config: EpistemicSubstrateConfig,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if tuple(sorted(paired_worlds)) != tuple(sorted(config.confirmatory_seeds)):
        failures.append("confirmatory cohort mismatch")
    for seed, metrics in paired_worlds.items():
        expected_arms = tuple(arm for _experiment, arm in sorted(config.experiments))
        if tuple(metric.arm for metric in metrics) != expected_arms:
            failures.append(f"seed {seed}: arm order/identity mismatch")
            continue
        for index, metric in enumerate(metrics):
            if metric.evidence_coverage != 1.0:
                failures.append(f"seed {seed} {metric.arm}: evidence coverage below 1")
            if metric.knowledge_survival_rate != 1.0:
                failures.append(f"seed {seed} {metric.arm}: knowledge survival below 1")
            if metric.false_synthesis_rate > config.maximum_false_synthesis_rate:
                failures.append(f"seed {seed} {metric.arm}: false synthesis gate failed")
            if index >= 2:
                provenance_loss = 1.0 - metric.provenance_completeness
                if provenance_loss > config.maximum_provenance_loss_graph_arms:
                    failures.append(f"seed {seed} {metric.arm}: provenance loss gate failed")
    return not failures, failures


def main() -> int:
    args = build_parser().parse_args()
    if args.confirmatory_seal != CONFIRMATORY_SEAL:
        raise SystemExit("invalid --confirmatory-seal")

    config, config_hash = load_epistemic_substrate_config(args.config)
    _validate_instrumentation_evidence(args.instrumentation_evidence, config, config_hash)

    paired_worlds = {
        seed: run_world(seed, config)
        for seed in config.confirmatory_seeds
    }
    quality_valid, quality_failures = _quality_gates(paired_worlds, config)
    analysis = analyze_confirmatory(paired_worlds, config)
    scientific_success = quality_valid and analysis.campaign_success

    results = [
        {
            "seed": seed,
            "arms": [metric.to_dict() for metric in paired_worlds[seed]],
        }
        for seed in config.confirmatory_seeds
    ]
    payload = {
        "campaign": config.name,
        "cohort": "confirmatory",
        "inferential": True,
        "config_hash": config_hash,
        "code_sha": args.code_sha,
        "seeds": list(config.confirmatory_seeds),
        "confirmatory_seeds_evaluated": True,
        "quality_gates_passed": quality_valid,
        "quality_gate_failures": quality_failures,
        "analysis": analysis.to_dict(),
        "scientific_success": scientific_success,
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if quality_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
