"""CLI for frozen Controlled Kick-Dose Experiment 136 discovery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .auction_margin_config import load_auction_margin_config
from .controlled_kick_dose_136 import run_experiment_136, write_experiment_136_outputs
from .controlled_kick_dose_config import load_controlled_kick_dose_config
from .lifecycle_corrections import install_lifecycle_corrections
from .runner import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--instrumentation-135", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dsn", default=os.getenv("RESONANCE_TEST_DSN"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dsn:
        raise SystemExit("--dsn or RESONANCE_TEST_DSN is required")
    install_lifecycle_corrections()
    config, config_hash = load_controlled_kick_dose_config(args.config)
    margin_config, _ = load_auction_margin_config(config.canonical_auction_margin_config)
    if (margin_config.near_radius, margin_config.probe_epsilon) != (
        config.target_radius,
        config.probe_epsilon,
    ):
        raise RuntimeError("canonical auction-margin controller no longer matches frozen kick controls")
    instrumentation = json.loads(Path(args.instrumentation_135).read_text(encoding="utf-8"))
    if not isinstance(instrumentation, dict):
        raise ValueError("Experiment 135 artifact must be a JSON object")
    with psycopg.connect(args.dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        result = run_experiment_136(
            connection,
            config=config,
            margin_config=margin_config,
            config_hash=config_hash,
            code_sha=args.code_sha,
            instrumentation_135=instrumentation,
        )
    write_experiment_136_outputs(result, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
