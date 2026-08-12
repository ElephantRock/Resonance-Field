"""Run non-inferential LLM Epistemic Substrate instrumentation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .epistemic_substrate_config import load_epistemic_substrate_config
from .llm_epistemic_config import load_llm_epistemic_config
from .llm_epistemic_corpus import CorpusManifest, load_corpus_manifest
from .llm_epistemic_instrumentation import InstrumentationGateError, run_instrumentation
from .llm_epistemic_openai import (
    DEFAULT_INSTRUMENTATION_MODEL,
    OpenAIEvaluatorClient,
    OpenAIProducerClient,
)
from .llm_epistemic_zai import (
    DEFAULT_ZAI_BASE_URL,
    DEFAULT_ZAI_MODEL,
    ZAIProducerClient,
)
from .llm_epistemic_zai_bounded import ZAIBudgetFinalizingEvaluatorClient
from .llm_epistemic_zai_retry import RetryingZAIClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--parent-config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", choices=("openai", "zai"), default="openai")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    return parser


def _clients(args: argparse.Namespace):
    if args.provider == "zai":
        if not os.getenv("ZAI_API_KEY"):
            raise SystemExit("ZAI_API_KEY is required for Z.AI stochastic instrumentation")
        model = args.model or DEFAULT_ZAI_MODEL
        base_url = args.base_url or DEFAULT_ZAI_BASE_URL
        retrying_client = RetryingZAIClient(base_url=base_url)
        return (
            ZAIProducerClient(model=model, base_url=base_url, client=retrying_client),
            ZAIBudgetFinalizingEvaluatorClient(
                model=model,
                base_url=base_url,
                client=retrying_client,
            ),
            model,
            base_url,
        )
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for OpenAI stochastic instrumentation")
    model = args.model or DEFAULT_INSTRUMENTATION_MODEL
    return OpenAIProducerClient(model=model), OpenAIEvaluatorClient(model=model), model, None


def _gate_failure_result(
    campaign_name: str,
    manifest: CorpusManifest,
    exc: InstrumentationGateError,
) -> dict[str, Any]:
    return {
        "campaign": campaign_name,
        "cohort": "instrumentation",
        "inferential": False,
        "confirmatory_access": False,
        "confirmatory_cases_evaluated": False,
        "status": "pre_replay_gate_failure",
        "manifest_sha256": manifest.sha256(),
        "case_count": 1,
        "cases": [exc.audit],
    }


def _write_result(path: str | Path, result: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    output.write_text(payload)
    print(payload, end="")


def main() -> int:
    args = build_parser().parse_args()
    campaign_config = load_llm_epistemic_config(args.config)
    parent_config, parent_config_hash = load_epistemic_substrate_config(args.parent_config)
    manifest = load_corpus_manifest(args.manifest)
    manifest.cases_for_instrumentation()
    producer, evaluator, model, base_url = _clients(args)
    exit_code = 0
    try:
        result = run_instrumentation(
            manifest,
            args.corpus_root,
            campaign_config,
            parent_config,
            producer,
            evaluator,
        )
    except InstrumentationGateError as exc:
        result = _gate_failure_result(campaign_config.name, manifest, exc)
        exit_code = 2
    result.update(
        {
            "requested_provider": args.provider,
            "requested_model": model,
            "provider_base_url": base_url,
            "code_sha": args.code_sha,
            "parent_config_hash": parent_config_hash,
        }
    )
    _write_result(args.output, result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
