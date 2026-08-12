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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--parent-config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=DEFAULT_INSTRUMENTATION_MODEL)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for stochastic instrumentation")
    campaign_config = load_llm_epistemic_config(args.config)
    parent_config, parent_config_hash = load_epistemic_substrate_config(args.parent_config)
    manifest = load_corpus_manifest(args.manifest)
    manifest.cases_for_instrumentation()
    producer = OpenAIProducerClient(model=args.model)
    evaluator = OpenAIEvaluatorClient(model=args.model)
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
            "requested_model": args.model,
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
