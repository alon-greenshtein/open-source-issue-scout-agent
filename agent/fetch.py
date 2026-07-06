"""GitHub REST API access layer.

Direct REST calls for now (requests-based). If the ADK + GitHub MCP spike
succeeds, this module gets replaced by an MCPToolset-backed equivalent with
the same function signatures, so filter.py/main.py don't need to change.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _paginated_get(url: str, params: dict) -> list[dict]:
    results = []
    params = {**params, "per_page": 100, "page": 1}
    while True:
        response = requests.get(url, headers=_headers(), params=params, timeout=30)
        response.raise_for_status()
        page = response.json()
        if not page:
            break
        results.extend(page)
        if len(page) < params["per_page"]:
            break
        params["page"] += 1
    return results


def get_open_issues(owner: str, repo: str) -> list[dict]:
    """Open issues only, metadata level (no comment bodies). Excludes PRs,
    which the GitHub issues endpoint otherwise mixes in."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    raw = _paginated_get(url, {"state": "open"})
    return [issue for issue in raw if "pull_request" not in issue]


def get_open_pull_requests(owner: str, repo: str) -> list[dict]:
    """Open PRs, with body text (needed to detect 'closes #N' references)."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    return _paginated_get(url, {"state": "open"})


def get_issue_comments(owner: str, repo: str, issue_number: int) -> list[dict]:
    """Full comment thread for a single issue. Only call this for the
    small shortlist that survives filter.py, not for every open issue."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    return _paginated_get(url, {})
