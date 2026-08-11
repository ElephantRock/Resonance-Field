"""Run the existing-evidence post-crossing reconvergence audit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .auction_margin_config import load_auction_margin_config
from .lifecycle_corrections import install_lifecycle_corrections
from .post_crossing_reconvergence_audit import (
    load_expected_records,
    run_post_crossing_audit,
    write_artifacts,
)
from .runner import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    parser.add_argument("--dsn", default=os.getenv("RESONANCE_TEST_DSN"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.dsn:
        raise SystemExit("--dsn or RESONANCE_TEST_DSN is required")
    install_lifecycle_corrections()
    config, config_hash = load_auction_margin_config(args.config)
    expected = load_expected_records(args.expected_dir)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    with psycopg.connect(args.dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        audit = run_post_crossing_audit(
            connection,
            config=config,
            config_hash=config_hash,
            expected_records=expected,
            audit_code_sha=args.code_sha,
        )
    write_artifacts(args.output_dir, audit)
    print(
        json.dumps(
            {key: value for key, value in audit.items() if key != "cycle_rows"},
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
