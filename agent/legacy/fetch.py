# GitHub REST API access layer — thin, faithful wrapper around GitHub's
# REST endpoints. Returns raw GitHub API dicts as-is; no shaping/renaming
# of fields happens here (that's main.py's job when it merges this data
# with scoring_agent.py's output for report.py).

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


# keep, when given, filters each page's items before they count against
# max_items — so max_items caps the items the caller actually wants (e.g.
# real issues), not raw API rows that may include entries filtered out
# later (e.g. PRs mixed into the issues endpoint).
def _paginated_get(
    url: str,
    params: dict,
    max_items: int | None = None,
    keep=lambda item: True,
) -> list[dict]:
    results = []
    params = {**params, "per_page": 100, "page": 1}
    while True:
        response = requests.get(url, headers=_headers(), params=params, timeout=30)
        response.raise_for_status()
        page = response.json()
        if not page:
            break
        results.extend(item for item in page if keep(item))
        if max_items is not None and len(results) >= max_items:
            return results[:max_items]
        if len(page) < params["per_page"]:
            break
        params["page"] += 1
    return results


# Open issues only, metadata level (no comment bodies). Excludes PRs, which
# the GitHub issues endpoint otherwise mixes in.
#
# max_issues caps how many issues we pull before filter.py/scoring_agent.py
# ever see them, so a repo with thousands of open issues (e.g. TypeScript)
# doesn't require paginating through all of them. sort=updated is a proxy
# for "still alive", not a ranking signal — the real ranking happens in
# filter.py (recency as one of three tie-breakers) and rank.py. For repos
# with fewer than max_issues open issues, this cap never triggers.
def get_open_issues(owner: str, repo: str, max_issues: int = 300) -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    return _paginated_get(
        url,
        {"state": "open", "sort": "updated", "direction": "desc"},
        max_items=max_issues,
        keep=lambda issue: "pull_request" not in issue,
    )


# Open PRs, with body text (needed to detect "closes #N" references).
#
# max_prs caps the same way as get_open_issues. Sorting by updated also
# improves claim-detection quality, not just speed: a PR that hasn't been
# touched in a long time is likely abandoned and a weaker "claimed" signal
# than a recently active PR closing the same issue.
def get_open_pull_requests(owner: str, repo: str, max_prs: int = 100) -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    return _paginated_get(
        url,
        {"state": "open", "sort": "updated", "direction": "desc"},
        max_items=max_prs,
    )


# Full comment thread for a single issue. Only call this for the small
# shortlist that survives filter.py, not for every open issue.
def get_issue_comments(owner: str, repo: str, issue_number: int) -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    return _paginated_get(url, {})
