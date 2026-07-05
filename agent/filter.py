"""Deterministic filtering + ranking of open issues (no LLM involved).

This runs before any LLM call so the expensive/judgment-requiring step
(scoring_agent.py) only ever sees a short, pre-cleaned shortlist.
"""

import re
from datetime import datetime, timezone

BEGINNER_LABELS = {"good first issue", "good-first-issue", "beginner", "easy", "help wanted"}
INTERMEDIATE_LABELS = {"intermediate", "medium"}
ADVANCED_LABELS = {"advanced", "hard", "hard difficulty"}

_CLOSES_PATTERN = re.compile(
    r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)",
    re.IGNORECASE,
)


def extract_linked_issue_numbers(pr_body: str | None) -> set[int]:
    """Issue numbers a PR body claims to close/fix/resolve."""
    if not pr_body:
        return set()
    return {int(match.group(2)) for match in _CLOSES_PATTERN.finditer(pr_body)}


def _label_names(issue: dict) -> set[str]:
    return {
        (label["name"] if isinstance(label, dict) else label).lower()
        for label in issue.get("labels", [])
    }


def _label_match_bonus(issue: dict, experience_level: str) -> int:
    labels = _label_names(issue)
    target = {
        "beginner": BEGINNER_LABELS,
        "intermediate": INTERMEDIATE_LABELS,
        "advanced": ADVANCED_LABELS,
    }.get(experience_level, set())
    return 1 if labels & target else 0


def _updated_at(issue: dict) -> datetime:
    raw = issue.get("updated_at")
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def filter_candidates(
    issues: list[dict],
    pull_requests: list[dict],
    experience_level: str = "beginner",
    max_candidates: int = 15,
) -> list[dict]:
    """Drop noise, rank what's left, return the top N survivors.

    Dropped: assigned issues, locked issues, issues already referenced
    by an open PR's "closes #N" (or fixes/resolves) text.
    Ranking: label match to experience_level first, then fewer comments
    (likely still unclaimed discussion), then most recently updated.
    """
    linked_issue_numbers: set[int] = set()
    for pr in pull_requests:
        linked_issue_numbers |= extract_linked_issue_numbers(pr.get("body"))

    survivors = [
        issue
        for issue in issues
        if not issue.get("assignees")
        and not issue.get("locked")
        and issue.get("number") not in linked_issue_numbers
    ]

    survivors.sort(
        key=lambda issue: (
            -_label_match_bonus(issue, experience_level),
            issue.get("comments", 0),
            -_updated_at(issue).timestamp(),
        )
    )

    return survivors[:max_candidates]
