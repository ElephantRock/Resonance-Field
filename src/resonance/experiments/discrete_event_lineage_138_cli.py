"""CLI for Experiment 138 schema-v1 lineage calibration."""

from __future__ import annotations

import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row

from .auction_margin_config import load_auction_margin_config
from .discrete_event_lineage_138 import (
    run_experiment_138_calibration,
    write_experiment_138_calibration_outputs,
)
from .lifecycle_corrections import install_lifecycle_corrections
from .lineage_instrumentation_config import load_lineage_config
from .runner import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dsn", default=os.getenv("RESONANCE_TEST_DSN"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dsn:
        raise SystemExit("--dsn or RESONANCE_TEST_DSN is required")
    install_lifecycle_corrections()
    config, config_hash = load_lineage_config(args.config)
    margin_config, _ = load_auction_margin_config(config.canonical_auction_margin_config)
    if (margin_config.near_radius, margin_config.probe_epsilon) != (
        config.target_radius,
        config.probe_epsilon,
    ):
        raise RuntimeError("canonical auction-margin controller no longer matches Experiment 138 root")
    with psycopg.connect(args.dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        result = run_experiment_138_calibration(
            connection,
            config=config,
            margin_config=margin_config,
            config_hash=config_hash,
            code_sha=args.code_sha,
        )
    write_experiment_138_calibration_outputs(result, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
