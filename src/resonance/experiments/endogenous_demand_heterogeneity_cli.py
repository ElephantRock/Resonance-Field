"""Reconstruct and audit historical Endogenous Demand 105–110 seed trajectories."""

from __future__ import annotations

import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row

from .endogenous_demand_config import load_endogenous_demand_config
from .endogenous_demand_heterogeneity import run_heterogeneity_audit, write_audit_artifacts
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
    config, config_hash = load_endogenous_demand_config(args.config)
    with psycopg.connect(args.dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        audit = run_heterogeneity_audit(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=args.code_sha,
        )
    write_audit_artifacts(args.output_dir, audit)
    print(json.dumps(audit, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
