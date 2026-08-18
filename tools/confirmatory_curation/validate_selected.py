#!/usr/bin/env python3
"""Validate selected confirmatory case bundles without executing any model or treatment."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from resonance.experiments.llm_epistemic_confirmatory_design import (
    _validate_case_against_rule,
    load_confirmatory_design,
)
from resonance.experiments.llm_epistemic_corpus import load_corpus_manifest


def _load_bundle(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"selected bundle must be an object: {path}")
    if value.get("bundle_version") != "1.0":
        raise ValueError(f"unsupported selected bundle version: {path}")
    if value.get("executable_confirmatory_manifest") is not False:
        raise ValueError(f"selected bundle must remain non-executable: {path}")
    for flag in ("treatment_execution", "evaluator_execution", "confirmatory_outcomes_observed"):
        if value.get(flag) is not False:
            raise ValueError(f"selected bundle has forbidden execution flag {flag}: {path}")
    if not isinstance(value.get("sources"), list) or not isinstance(value.get("cases"), list):
        raise ValueError(f"selected bundle requires sources and cases arrays: {path}")
    return value


def validate_selected_bundles(selected_root: str | Path, design_path: str | Path) -> dict[str, Any]:
    root = Path(selected_root)
    paths = sorted(root.glob("*.json"))
    if not paths:
        raise ValueError("no selected case bundles found")
    design = load_confirmatory_design(design_path)

    raw_sources: list[dict[str, Any]] = []
    raw_cases: list[dict[str, Any]] = []
    bundle_names: list[str] = []
    for path in paths:
        bundle = _load_bundle(path)
        bundle_names.append(path.name)
        raw_sources.extend(bundle["sources"])
        raw_cases.extend(bundle["cases"])

    source_ids = [str(source.get("source_id", "")) for source in raw_sources]
    case_ids = [str(case.get("case_id", "")) for case in raw_cases]
    source_hashes = [str(source.get("sha256", "")).lower() for source in raw_sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("selected bundles reuse source_id values")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("selected bundles reuse case_id values")
    if len(source_hashes) != len(set(source_hashes)):
        raise ValueError("selected bundles reuse exact frozen source bytes")

    manifest_payload = {
        "manifest_version": "1.0",
        "sources": raw_sources,
        "cases": raw_cases,
    }
    with tempfile.TemporaryDirectory() as temporary:
        manifest_path = Path(temporary) / "partial-manifest.json"
        manifest_path.write_text(json.dumps(manifest_payload, indent=2) + "\n")
        manifest = load_corpus_manifest(manifest_path)

    source_by_id = {source.source_id: source for source in manifest.sources}
    cell_counts: Counter[tuple[str, str]] = Counter()
    project_cases: Counter[str] = Counter()
    organization_cases: Counter[str] = Counter()
    for case in manifest.cases:
        if case.domain_id not in design.domains:
            raise ValueError(f"selected case {case.case_id} has invalid domain_id")
        if case.challenge_type not in design.challenges:
            raise ValueError(f"selected case {case.case_id} has invalid challenge_type")
        challenge = str(case.challenge_type)
        _validate_case_against_rule(case, design.rule(challenge), source_by_id)
        cell_counts[(str(case.domain_id), challenge)] += 1
        projects = {str(source_by_id[source_id].upstream_project_id) for source_id in case.source_ids}
        organizations = {
            str(source_by_id[source_id].upstream_organization_id) for source_id in case.source_ids
        }
        for project in projects:
            project_cases[project] += 1
        for organization in organizations:
            organization_cases[organization] += 1

    if max(project_cases.values(), default=0) > design.maximum_cases_per_upstream_project:
        raise ValueError("selected bundles already exceed upstream project case cap")
    if max(organization_cases.values(), default=0) > design.maximum_cases_per_upstream_organization:
        raise ValueError("selected bundles already exceed upstream organization case cap")
    if any(count > design.cases_per_cell for count in cell_counts.values()):
        raise ValueError("selected bundles exceed a frozen domain/challenge cell capacity")

    return {
        "bundle_count": len(paths),
        "case_count": len(manifest.cases),
        "source_count": len(manifest.sources),
        "unique_source_sha256_count": len(set(source_hashes)),
        "cell_counts": {
            f"{domain}/{challenge}": count
            for (domain, challenge), count in sorted(cell_counts.items())
        },
        "treatment_execution": False,
        "evaluator_execution": False,
        "confirmatory_outcomes_observed": False,
        "bundles": bundle_names,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-root", required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record = validate_selected_bundles(args.selected_root, args.design)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
