#!/usr/bin/env python3
"""Validate and cryptographically seal the held-out 142–145 confirmatory corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from resonance.experiments.llm_epistemic_confirmatory_seal import build_confirmatory_seal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--preseal-code-sha", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record = build_confirmatory_seal(
        repo_root=args.repo_root,
        manifest_path=args.manifest,
        corpus_root=args.corpus_root,
        campaign_config_path=args.config,
        parent_config_path=args.parent_config,
        design_path=args.design,
        preseal_code_sha=args.preseal_code_sha,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
