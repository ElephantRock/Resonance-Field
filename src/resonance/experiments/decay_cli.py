"""Command-line entry point for Experiment 002 decay stress runs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .decay_models import load_decay_experiment_config
from .decay_runner import run_decay_experiment
from .runner import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument(
        "--arm",
        required=True,
        choices=("fast_decay", "slow_decay", "no_decay"),
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    parser.add_argument("--dsn", default=os.getenv("RESONANCE_TEST_DSN"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.dsn:
        raise SystemExit("--dsn or RESONANCE_TEST_DSN is required")
    config, config_hash = load_decay_experiment_config(args.config)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    with psycopg.connect(args.dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        summary = run_decay_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            seed=args.seed,
            arm=args.arm,
            code_sha=args.code_sha,
            output_dir=args.output_dir,
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
