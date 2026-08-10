"""Create or replace one GitHub issue comment identified by an HTML marker."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

_API_VERSION = "2022-11-28"


def _request(url: str, *, token: str, method: str = "GET", payload: dict[str, object] | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": _API_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "resonance-field-lab-notebook",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} failed: {exc.code} {body}") from exc


def _find_existing(repo: str, issue: int, marker: str, *, token: str):
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repo}/issues/{issue}/comments"
            f"?per_page=100&page={page}"
        )
        comments = _request(url, token=token)
        if not isinstance(comments, list):
            raise RuntimeError("GitHub comments response must be a list")
        existing = next(
            (
                item
                for item in comments
                if isinstance(item, dict) and marker in str(item.get("body", ""))
            ),
            None,
        )
        if existing is not None:
            return existing
        if len(comments) < 100:
            return None
        page += 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--token", default=os.getenv("GH_TOKEN"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.token:
        raise SystemExit("--token or GH_TOKEN is required")
    body = Path(args.body_file).read_text()
    first_line = body.splitlines()[0] if body.splitlines() else ""
    if not first_line.startswith("<!--") or not first_line.endswith("-->"):
        raise SystemExit("body file must start with a stable HTML marker")

    existing = _find_existing(args.repo, args.issue, first_line, token=args.token)
    if existing is None:
        target = f"https://api.github.com/repos/{args.repo}/issues/{args.issue}/comments"
        result = _request(target, token=args.token, method="POST", payload={"body": body})
        print(f"created comment {result['id']}")
    else:
        target = f"https://api.github.com/repos/{args.repo}/issues/comments/{existing['id']}"
        result = _request(target, token=args.token, method="PATCH", payload={"body": body})
        print(f"updated comment {result['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
