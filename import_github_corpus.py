from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_json(url: str, token: str | None = None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "docintel-importer/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only GitHub docs/issues importer")
    parser.add_argument("--repo", required=True, help="owner/name, for example fastapi/fastapi")
    parser.add_argument("--output", required=True)
    parser.add_argument("--issues", type=int, default=100)
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    args = parser.parse_args()

    output = Path(args.output)
    docs = output / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    readme = get_json(f"https://api.github.com/repos/{args.repo}/readme", args.token)
    readme_text = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")
    (docs / "README.md").write_text(readme_text, encoding="utf-8")

    issues: list[dict] = []
    page = 1
    while len(issues) < args.issues:
        batch = get_json(
            f"https://api.github.com/repos/{args.repo}/issues?state=closed&per_page=100&page={page}",
            args.token,
        )
        if not batch:
            break
        for issue in batch:
            if "pull_request" in issue:
                continue
            issues.append({
                "id": f"{args.repo}#{issue['number']}",
                "issue_id": str(issue["number"]),
                "title": issue.get("title", ""),
                "body": issue.get("body", "") or "",
                "state": issue.get("state", ""),
                "accepted_answer": "",
                "url": issue.get("html_url", ""),
                "repository": args.repo,
                "comments": [],
            })
            if len(issues) >= args.issues:
                break
        page += 1
        time.sleep(0.2)

    with (output / "issues.jsonl").open("w", encoding="utf-8") as handle:
        for row in issues:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"repo": args.repo, "output": str(output), "issues": len(issues), "accepted_answer_policy": "manual_gold_only"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

