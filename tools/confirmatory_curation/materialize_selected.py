#!/usr/bin/env python3
"""Materialize selected held-out source bytes and a manifest from curation bundles.

This is a curation/integrity utility, not scientific execution. It downloads
only immutable commit-pinned GitHub files, verifies both Git blob SHA and the
previously frozen SHA-256, writes the selected source tree, and constructs the
manifest consumed by the separately frozen seal code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from resonance.experiments.llm_epistemic_confirmatory_design import (
    load_confirmatory_design,
    validate_confirmatory_manifest_against_design,
)
from resonance.experiments.llm_epistemic_corpus import load_corpus_manifest


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_blob_sha(value: bytes) -> str:
    header = f"blob {len(value)}\0".encode()
    return hashlib.sha1(header + value, usedforsecurity=False).hexdigest()


def _raw_url(repository: str, commit_sha: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repository}/{commit_sha}/{path}"


def _download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Resonance-Field-Confirmatory-Curation/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError(f"unexpected HTTP status {response.status}: {url}")
            return response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to acquire {url}: {exc}") from exc


def _bundles(selected_root: Path) -> tuple[dict[str, Any], ...]:
    values: list[dict[str, Any]] = []
    for path in sorted(selected_root.glob("*.json")):
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or value.get("bundle_version") != "1.0":
            raise ValueError(f"invalid selected bundle: {path}")
        if value.get("executable_confirmatory_manifest") is not False:
            raise ValueError(f"selected bundle unexpectedly marked executable: {path}")
        values.append(value)
    if not values:
        raise ValueError("no selected bundles found")
    return tuple(values)


def materialize_selected(
    *,
    selected_root: str | Path,
    output_root: str | Path,
    design_path: str | Path,
    require_full: bool,
    timeout: float = 30.0,
) -> dict[str, Any]:
    selected = Path(selected_root)
    output = Path(output_root)
    bundles = _bundles(selected)

    sources: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for bundle in bundles:
        for raw_source in bundle["sources"]:
            source = dict(raw_source)
            pin = source.pop("pin", None)
            if not isinstance(pin, dict):
                raise ValueError(f"selected source lacks immutable pin: {source.get('source_id')}")
            source_id = str(source["source_id"])
            if source_id in seen_ids:
                raise ValueError(f"duplicate selected source_id: {source_id}")
            seen_ids.add(source_id)
            expected_sha = str(source["sha256"]).lower()
            if expected_sha in seen_hashes:
                raise ValueError(f"duplicate selected source bytes: {source_id}")
            seen_hashes.add(expected_sha)

            repository = str(source["upstream_project_id"])
            commit_sha = str(pin["commit_sha"])
            path = str(pin["path"])
            expected_blob = str(pin["git_blob_sha"]).lower()
            content = _download(_raw_url(repository, commit_sha, path), timeout)
            observed_blob = _git_blob_sha(content)
            observed_sha = _sha256(content)
            if observed_blob != expected_blob:
                raise ValueError(
                    f"Git blob mismatch for {source_id}: {observed_blob} != {expected_blob}"
                )
            if observed_sha != expected_sha:
                raise ValueError(
                    f"SHA-256 mismatch for {source_id}: {observed_sha} != {expected_sha}"
                )
            local_path = output / str(source["local_path"])
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            sources.append(source)
        cases.extend(dict(case) for case in bundle["cases"])

    manifest_payload = {
        "manifest_version": "1.0",
        "sources": sources,
        "cases": cases,
    }
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n")
    manifest = load_corpus_manifest(manifest_path)

    full_design_validated = False
    if require_full:
        design = load_confirmatory_design(design_path)
        validate_confirmatory_manifest_against_design(manifest, design)
        full_design_validated = True

    record = {
        "record_version": "1.0",
        "bundle_count": len(bundles),
        "case_count": len(manifest.cases),
        "source_count": len(manifest.sources),
        "unique_source_sha256_count": len(seen_hashes),
        "manifest_canonical_sha256": manifest.sha256(),
        "manifest_file_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "full_design_validation_required": require_full,
        "full_design_validated": full_design_validated,
        "treatment_execution": False,
        "evaluator_execution": False,
        "confirmatory_outcomes_observed": False,
    }
    (output / "materialization-record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--require-full", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record = materialize_selected(
        selected_root=args.selected_root,
        output_root=args.output_root,
        design_path=args.design,
        require_full=args.require_full,
        timeout=args.timeout,
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
