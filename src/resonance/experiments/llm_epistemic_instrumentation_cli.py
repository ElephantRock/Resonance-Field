"""Run non-inferential LLM Epistemic Substrate instrumentation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .epistemic_substrate_config import load_epistemic_substrate_config
from .llm_epistemic_config import load_llm_epistemic_config
from .llm_epistemic_corpus import load_corpus_manifest
from .llm_epistemic_instrumentation import run_instrumentation
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


def main() -> int:
    args = build_parser().parse_args()
    campaign_config = load_llm_epistemic_config(args.config)
    parent_config, parent_config_hash = load_epistemic_substrate_config(args.parent_config)
    manifest = load_corpus_manifest(args.manifest)
    manifest.cases_for_instrumentation()
    producer, evaluator, model, base_url = _clients(args)
    result = run_instrumentation(
        manifest,
        args.corpus_root,
        campaign_config,
        parent_config,
        producer,
        evaluator,
    )
    result.update(
        {
            "requested_provider": args.provider,
            "requested_model": model,
            "provider_base_url": base_url,
            "code_sha": args.code_sha,
            "parent_config_hash": parent_config_hash,
        }
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
