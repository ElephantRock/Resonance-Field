"""CLI for the adaptive Experiments 004-013 campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adaptive_campaign import load_campaign_config, run_campaign


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    config, config_hash = load_campaign_config(args.config)
    summary = run_campaign(
        config,
        code_sha=args.code_sha,
        output_dir=args.output_dir,
    )
    metadata = {
        "config_hash": config_hash,
        "config_path": str(Path(args.config)),
        "final_label": summary["final_label"],
        "validated": summary["validated"],
    }
    (Path(args.output_dir) / "run-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(metadata, sort_keys=True))


if __name__ == "__main__":
    main()
