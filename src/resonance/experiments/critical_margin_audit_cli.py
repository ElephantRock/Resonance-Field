"""Run the existing-evidence Critical-Margin Audit for Experiments 105–128."""

from __future__ import annotations

import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row

from .chaos_predictability_config import load_chaos_predictability_config
from .critical_margin_audit import run_critical_margin_audit, write_artifacts
from .endogenous_demand_config import load_endogenous_demand_config
from .lifecycle_corrections import install_lifecycle_corrections
from .runner import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endogenous-config", required=True)
    parser.add_argument("--chaos-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--code-sha", default=os.getenv("GITHUB_SHA", "local"))
    parser.add_argument("--dsn", default=os.getenv("RESONANCE_TEST_DSN"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.dsn:
        raise SystemExit("--dsn or RESONANCE_TEST_DSN is required")
    install_lifecycle_corrections()
    endogenous, endogenous_hash = load_endogenous_demand_config(args.endogenous_config)
    chaos, chaos_hash = load_chaos_predictability_config(args.chaos_config)
    with psycopg.connect(args.dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        audit = run_critical_margin_audit(
            connection,
            endogenous_config=endogenous,
            endogenous_config_hash=endogenous_hash,
            chaos_protocol=chaos,
            chaos_config_hash=chaos_hash,
            code_sha=args.code_sha,
        )
    write_artifacts(args.output_dir, audit)
    printable = dict(audit)
    printable.pop("cycle_rows", None)
    print(json.dumps(printable, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
