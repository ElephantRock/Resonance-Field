"""Execute or aggregate sealed confirmatory Experiments 142–145 without case replacement."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .llm_epistemic_confirmatory_execution import (
    ConfirmatoryProtocolError,
    aggregate_confirmatory_results,
    load_sealed_confirmatory_inputs,
    run_confirmatory_case,
)
from .llm_epistemic_zai import ZAIProducerClient
from .llm_epistemic_zai_bounded import ZAIBudgetFinalizingEvaluatorClient
from .llm_epistemic_zai_retry import RetryingZAIClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("case", "aggregate"))
    parser.add_argument("--seal", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument(
        "--config",
        default="configs/experiments/llm-epistemic-substrate-142-145.json",
    )
    parser.add_argument(
        "--parent-config",
        default="configs/experiments/epistemic-substrate-138-141.json",
    )
    parser.add_argument(
        "--design",
        default="configs/experiments/llm-epistemic-substrate-142-145-confirmatory-design.json",
    )
    parser.add_argument("--case-id")
    parser.add_argument("--results-dir")
    parser.add_argument("--output", required=True)
    return parser


def _write(path: str | Path, value: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _load_controls(args: argparse.Namespace):
    return load_sealed_confirmatory_inputs(
        seal_path=args.seal,
        repo_root=args.repo_root,
        manifest_path=args.manifest,
        campaign_config_path=args.config,
        parent_config_path=args.parent_config,
        design_path=args.design,
    )


def _case_mode(args: argparse.Namespace) -> int:
    if not args.case_id:
        raise SystemExit("--case-id is required in case mode")
    if not os.getenv("ZAI_API_KEY"):
        raise SystemExit("ZAI_API_KEY is required for sealed confirmatory case execution")

    seal, manifest, campaign, parent, _design = _load_controls(args)
    case_by_id = {case.case_id: case for case in manifest.cases}
    case = case_by_id.get(args.case_id)
    if case is None:
        raise SystemExit(f"case id is not present in the sealed manifest: {args.case_id}")

    client = RetryingZAIClient(
        base_url=campaign.provider_base_url,
        max_retries=campaign.provider_maximum_transient_retries,
        expected_response_model=campaign.expected_response_model,
    )
    producer = ZAIProducerClient(
        model=campaign.requested_model,
        base_url=campaign.provider_base_url,
        temperature=campaign.provider_temperature,
        client=client,
    )
    evaluator = ZAIBudgetFinalizingEvaluatorClient(
        model=campaign.requested_model,
        base_url=campaign.provider_base_url,
        max_tool_rounds=campaign.maximum_retrieval_tool_rounds,
        per_call_retrieval_budget=campaign.per_call_retrieval_budget,
        temperature=campaign.provider_temperature,
        client=client,
    )
    try:
        result = run_confirmatory_case(
            case=case,
            manifest=manifest,
            corpus_root=args.corpus_root,
            campaign=campaign,
            substrate_config=parent,
            producer_client=producer,
            evaluator_client=evaluator,
            seal_sha256=str(seal["seal_sha256"]),
        )
    except Exception as exc:
        audit = exc.audit if isinstance(exc, ConfirmatoryProtocolError) else {}
        failure = {
            "status": "execution_failure",
            "case_id": case.case_id,
            "cohort": "confirmatory",
            "seal_sha256": str(seal["seal_sha256"]),
            "campaign_admissible": False,
            "campaign_success": None,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "audit": audit,
        }
        _write(args.output, failure)
        return 2
    _write(args.output, result)
    return 0


def _aggregate_mode(args: argparse.Namespace) -> int:
    if not args.results_dir:
        raise SystemExit("--results-dir is required in aggregate mode")
    seal, manifest, campaign, _parent, design = _load_controls(args)
    files = sorted(Path(args.results_dir).glob("*.json"))
    results: list[dict[str, Any]] = []
    for path in files:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise SystemExit(f"result file is not a JSON object: {path}")
        results.append(value)
    output = aggregate_confirmatory_results(
        results=results,
        manifest=manifest,
        campaign=campaign,
        design=design,
        seal_sha256=str(seal["seal_sha256"]),
    )
    _write(args.output, output)
    return 0 if output.get("campaign_admissible") is True else 2


def main() -> int:
    args = build_parser().parse_args()
    if args.mode == "case":
        return _case_mode(args)
    return _aggregate_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
