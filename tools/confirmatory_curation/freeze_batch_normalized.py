#!/usr/bin/env python3
"""Normalize split source pins, then run the confirmatory curation freezer.

This utility is curation-only and remains outside the frozen scientific
implementation. Existing acquisition plans with ordinary SHA strings are passed
through unchanged; plans may alternatively store 40-character source pins as
ordered eight-character parts for transport-safe repository writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from freeze_batch import freeze_batch


def _join_pin_parts(source: dict[str, Any], key: str) -> bool:
    if key in source:
        return False
    parts_key = f"{key}_parts"
    parts = source.get(parts_key)
    if not isinstance(parts, list) or not parts or not all(isinstance(part, str) for part in parts):
        return False
    source[key] = "".join(parts)
    return True


def freeze_normalized(
    plan_path: str | Path,
    output_dir: str | Path,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    plan_file = Path(plan_path)
    raw_plan = plan_file.read_bytes()
    plan = json.loads(raw_plan)
    if not isinstance(plan, dict):
        raise ValueError("curation acquisition plan must be a JSON object")

    changed = False
    raw_sources = plan.get("sources")
    if isinstance(raw_sources, list):
        for source in raw_sources:
            if isinstance(source, dict):
                changed |= _join_pin_parts(source, "commit_sha")
                changed |= _join_pin_parts(source, "git_blob_sha")

    if not changed:
        return freeze_batch(plan_file, output_dir, timeout=timeout)

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
        json.dump(plan, handle, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        record = freeze_batch(handle.name, output_dir, timeout=timeout)

    record["plan_sha256"] = hashlib.sha256(raw_plan).hexdigest()
    output = Path(output_dir)
    (output / "freeze-record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record = freeze_normalized(args.plan, args.output_dir, timeout=args.timeout)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
