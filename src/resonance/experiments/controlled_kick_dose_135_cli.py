"""Run Experiment 135 controlled kick-dose instrumentation."""

from __future__ import annotations

import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row

from .auction_margin_config import load_auction_margin_config
from .controlled_kick_dose_campaign import run_experiment_135, write_experiment_135_outputs
from .controlled_kick_dose_config import load_controlled_kick_dose_config
from .lifecycle_corrections import install_lifecycle_corrections
from .runner import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    parser.add_argument("--dsn", default=os.getenv("RESONANCE_TEST_DSN"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
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
    with psycopg.connect(args.dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        result = run_experiment_135(
            connection,
            config=config,
            margin_config=margin_config,
            config_hash=config_hash,
            code_sha=args.code_sha,
        )
    write_experiment_135_outputs(result, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if bool(result["instrumentation_validated"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
