#!/usr/bin/env python3
"""Freeze commit-pinned public source bytes for confirmatory corpus curation.

This utility is intentionally outside the frozen scientific implementation. It
performs acquisition/integrity work only: no producers, substrates, evaluators,
scoring, or analysis are executed. Final scientific execution is still gated by
the separately frozen confirmatory design and cryptographic seal.
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

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_blob_sha(value: bytes) -> str:
    header = f"blob {len(value)}\0".encode()
    return hashlib.sha1(header + value, usedforsecurity=False).hexdigest()


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _raw_url(repository: str, commit_sha: str, path: str) -> str:
    if repository.count("/") != 1:
        raise ValueError("repository must use owner/name form")
    if not _HEX40.fullmatch(commit_sha):
        raise ValueError("commit_sha must be a 40-character lowercase SHA")
    if path.startswith("/") or ".." in Path(path).parts:
        raise ValueError("path must be repository-relative without traversal")
    return f"https://raw.githubusercontent.com/{repository}/{commit_sha}/{path}"


def _blob_url(repository: str, commit_sha: str, path: str) -> str:
    return f"https://github.com/{repository}/blob/{commit_sha}/{path}"


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


def freeze_batch(
    plan_path: str | Path,
    output_dir: str | Path,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    plan_file = Path(plan_path)
    output = Path(output_dir)
    raw_plan = plan_file.read_bytes()
    plan = json.loads(raw_plan)
    if not isinstance(plan, dict):
        raise ValueError("curation acquisition plan must be a JSON object")
    if plan.get("plan_version") != "1.0":
        raise ValueError("unsupported curation acquisition plan version")
    if plan.get("cohort") != "confirmatory":
        raise PermissionError("curation freezer accepts confirmatory material only")
    if plan.get("treatment_execution") is not True:
        raise PermissionError("curation freezer accepts confirmatory material only")
    if plan.get("evaluator_execution") is not False:
        raise ValueError("curation acquisition plan may not execute evaluators")
    if plan.get("confirmatory_outcomes_observed") is not False:
        raise ValueError("curation acquisition plan may not observe outcomes")
    acquired_at = _required_string(plan, "acquired_at")

    raw_sources = plan.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("curation acquisition plan sources must be a non-empty array")

    source_dir = output / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    seen_ids: set[str] = set()
    observed_content_hashes: set[str] = set()
    frozen: list[dict[str, Any]] = []

    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ValueError("each source must be an object")
        source_id = _required_string(raw_source, "source_id")
        if not _SAFE_ID.fullmatch(source_id):
            raise ValueError(f"unsafe source_id: {source_id}")
        if source_id in seen_ids:
            raise ValueError(f"duplicate source_id: {source_id}")
        seen_ids.add(source_id)

        repository = _required_string(raw_source, "repository")
        commit_sha = _required_string(raw_source, "commit_sha").lower()
        path = _required_string(raw_source, "path")
        expected_blob = _required_string(raw_source, "git_blob_sha").lower()
        if not _HEX40.fullmatch(expected_blob):
            raise ValueError("git_blob_sha must be a 40-character lowercase SHA")
        evidence_observed_at = _required_string(raw_source, "evidence_observed_at")
        upstream_project_id = _required_string(raw_source, "upstream_project_id")
        upstream_organization_id = _required_string(raw_source, "upstream_organization_id")
        media_type = _required_string(raw_source, "media_type")
        title = _required_string(raw_source, "title")

        url = _raw_url(repository, commit_sha, path)
        content = _download(url, timeout)
        observed_blob = _git_blob_sha(content)
        if observed_blob != expected_blob:
            raise ValueError(
                f"Git blob mismatch for {source_id}: expected {expected_blob}, observed {observed_blob}"
            )
        content_sha = _sha256(content)
        if content_sha in observed_content_hashes:
            raise ValueError(f"duplicate exact source bytes inside batch: {source_id}")
        observed_content_hashes.add(content_sha)

        suffix = Path(path).suffix or ".txt"
        local_rel = f"sources/{source_id}{suffix}"
        local_path = output / local_rel
        local_path.write_bytes(content)
        frozen.append(
            {
                "source_id": source_id,
                "repository": repository,
                "commit_sha": commit_sha,
                "path": path,
                "git_blob_sha": observed_blob,
                "sha256": content_sha,
                "bytes": len(content),
                "media_type": media_type,
                "title": title,
                "acquired_at": acquired_at,
                "evidence_observed_at": evidence_observed_at,
                "upstream_project_id": upstream_project_id,
                "upstream_organization_id": upstream_organization_id,
                "local_path": local_rel,
                "canonical_url": _blob_url(repository, commit_sha, path),
            }
        )

    output.mkdir(parents=True, exist_ok=True)
    record = {
        "record_version": "1.0",
        "cohort": "confirmatory",
        "candidate_id": plan.get("candidate_id"),
        "plan_sha256": _sha256(raw_plan),
        "source_count": len(frozen),
        "acquired_at": acquired_at,
        "treatment_execution": False,
        "evaluator_execution": False,
        "confirmatory_outcomes_observed": False,
        "sources": frozen,
    }
    (output / "freeze-record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
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
    record = freeze_batch(args.plan, args.output_dir, timeout=args.timeout)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
