"""Freeze immutable naturalistic sources for LLM epistemic instrumentation.

This is a curation tool, not an evaluator. It downloads only commit-pinned raw
GitHub files declared in an instrumentation acquisition plan, verifies the Git
blob SHA, computes SHA-256, writes local snapshots, and emits a corpus manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from resonance.experiments.llm_epistemic_corpus import load_corpus_manifest

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_blob_sha(value: bytes) -> str:
    header = f"blob {len(value)}\0".encode()
    return hashlib.sha1(header + value, usedforsecurity=False).hexdigest()


def _require_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _raw_url(repository: str, commit_sha: str, path: str) -> str:
    if repository.count("/") != 1:
        raise ValueError("repository must use owner/name form")
    if not _HEX40.fullmatch(commit_sha):
        raise ValueError("commit_sha must be a 40-character lowercase hex SHA")
    if path.startswith("/") or ".." in Path(path).parts:
        raise ValueError("source path must be repository-relative without traversal")
    return f"https://raw.githubusercontent.com/{repository}/{commit_sha}/{path}"


def _github_blob_url(repository: str, commit_sha: str, path: str) -> str:
    return f"https://github.com/{repository}/blob/{commit_sha}/{path}"


def _download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Resonance-Field-Epistemic-Curation/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError(f"unexpected HTTP status {response.status} for {url}")
            return response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to acquire frozen source {url}: {exc}") from exc


def freeze_plan(plan_path: str | Path, output_dir: str | Path, *, timeout: float = 30.0) -> dict[str, Any]:
    plan_path = Path(plan_path)
    output_dir = Path(output_dir)
    raw_plan = plan_path.read_bytes()
    plan = json.loads(raw_plan)
    if not isinstance(plan, dict):
        raise ValueError("acquisition plan must be a JSON object")
    if plan.get("plan_version") != "1.0":
        raise ValueError("unsupported acquisition plan version")
    if plan.get("cohort") != "instrumentation":
        raise PermissionError("source freezer may only acquire instrumentation material")
    raw_sources = plan.get("sources")
    raw_cases = plan.get("cases")
    if not isinstance(raw_sources, list) or not isinstance(raw_cases, list):
        raise ValueError("acquisition plan sources and cases must be arrays")
    if any(not isinstance(case, dict) or case.get("cohort") != "instrumentation" for case in raw_cases):
        raise PermissionError("acquisition plan contains non-instrumentation cases")

    source_dir = output_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    manifest_sources: list[dict[str, Any]] = []
    freeze_sources: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ValueError("each acquisition source must be an object")
        source_id = _require_string(raw_source, "source_id")
        if not _SAFE_ID.fullmatch(source_id):
            raise ValueError(f"unsafe source_id: {source_id}")
        if source_id in seen_ids:
            raise ValueError(f"duplicate source_id: {source_id}")
        seen_ids.add(source_id)
        repository = _require_string(raw_source, "repository")
        commit_sha = _require_string(raw_source, "commit_sha")
        path = _require_string(raw_source, "path")
        expected_blob = _require_string(raw_source, "git_blob_sha").lower()
        if not _HEX40.fullmatch(expected_blob):
            raise ValueError("git_blob_sha must be a 40-character lowercase hex SHA")
        url = _raw_url(repository, commit_sha, path)
        content = _download(url, timeout)
        observed_blob = _git_blob_sha(content)
        if observed_blob != expected_blob:
            raise ValueError(
                f"Git blob mismatch for {source_id}: expected {expected_blob}, observed {observed_blob}"
            )
        suffix = Path(path).suffix or ".txt"
        local_rel = f"sources/{source_id}{suffix}"
        local_path = output_dir / local_rel
        local_path.write_bytes(content)
        content_sha256 = _sha256(content)
        manifest_sources.append(
            {
                "source_id": source_id,
                "sha256": content_sha256,
                "media_type": _require_string(raw_source, "media_type"),
                "title": _require_string(raw_source, "title"),
                "acquired_at": _require_string(raw_source, "acquired_at"),
                "local_path": local_rel,
                "canonical_url": _github_blob_url(repository, commit_sha, path),
            }
        )
        freeze_sources.append(
            {
                "source_id": source_id,
                "repository": repository,
                "commit_sha": commit_sha,
                "path": path,
                "git_blob_sha": observed_blob,
                "sha256": content_sha256,
                "bytes": len(content),
            }
        )

    manifest_payload = {
        "manifest_version": "1.0",
        "sources": manifest_sources,
        "cases": raw_cases,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n")
    manifest = load_corpus_manifest(manifest_path)
    manifest.cases_for_instrumentation()
    record = {
        "plan_sha256": _sha256(raw_plan),
        "manifest_sha256": manifest.sha256(),
        "cohort": "instrumentation",
        "confirmatory_access": False,
        "sources": freeze_sources,
    }
    (output_dir / "freeze-record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record = freeze_plan(args.plan, args.output_dir, timeout=args.timeout)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
