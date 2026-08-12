"""Run non-inferential instrumentation for Epistemic Substrate Experiments 138–141."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .epistemic_substrate_campaign import run_world
from .epistemic_substrate_config import load_epistemic_substrate_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    return parser


def _quality_gates(results: list[dict[str, object]], maximum_false_synthesis_rate: float) -> bool:
    for world in results:
        arms = world["arms"]
        assert isinstance(arms, list)
        for index, arm in enumerate(arms):
            assert isinstance(arm, dict)
            if float(arm["evidence_coverage"]) != 1.0:
                return False
            if float(arm["knowledge_survival_rate"]) != 1.0:
                return False
            if float(arm["false_synthesis_rate"]) > maximum_false_synthesis_rate:
                return False
            if index >= 2 and float(arm["provenance_completeness"]) != 1.0:
                return False
    return True


def main() -> int:
    args = build_parser().parse_args()
    config, config_hash = load_epistemic_substrate_config(args.config)
    results: list[dict[str, object]] = []
    for seed in config.instrumentation_seeds:
        arms = [metric.to_dict() for metric in run_world(seed, config)]
        results.append({"seed": seed, "arms": arms})

    validated = _quality_gates(results, config.maximum_false_synthesis_rate)
    payload = {
        "campaign": config.name,
        "cohort": "instrumentation",
        "inferential": False,
        "config_hash": config_hash,
        "code_sha": args.code_sha,
        "seeds": list(config.instrumentation_seeds),
        "confirmatory_seeds_evaluated": False,
        "instrumentation_validated": validated,
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if validated else 2


if __name__ == "__main__":
    raise SystemExit(main())
