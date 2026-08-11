"""Run one checkpointed Auction Margin Control experiment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .auction_margin_checkpoint import load_checkpoint, run_auction_margin_step
from .auction_margin_config import load_auction_margin_config
from .lifecycle_corrections import install_lifecycle_corrections
from .runner import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--experiment", required=True, type=int)
    parser.add_argument("--checkpoint-in")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    parser.add_argument("--dsn", default=os.getenv("RESONANCE_TEST_DSN"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.dsn:
        raise SystemExit("--dsn or RESONANCE_TEST_DSN is required")
    install_lifecycle_corrections()
    protocol, config_hash = load_auction_margin_config(args.config)
    checkpoint = load_checkpoint(args.checkpoint_in) if args.checkpoint_in else None
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    with psycopg.connect(args.dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        result = run_auction_margin_step(
            connection,
            protocol=protocol,
            config_hash=config_hash,
            code_sha=args.code_sha,
            number=args.experiment,
            checkpoint=checkpoint,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
