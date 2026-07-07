# Deterministic filtering + ranking of open issues (no LLM involved).
#
# Drops: assigned issues, locked issues, issues already referenced by an
# open PR's "closes/fixes/resolves #N" text.
# Ranks by: label match to experience_level, then most recently updated,
# then comment count (light tie-breaker only, not a strong signal).
# This runs before any LLM call so scoring_agent.py only ever sees a
# short, pre-cleaned shortlist.

import re
from datetime import datetime, timezone

# "intermediate"/"advanced" labels have no widely-adopted GitHub convention, so this
# dict mostly won't match for those levels — ranking falls back to recency/comments.
# That's fine: this only affects which ~15 candidates reach the LLM, not the final
# top-5 (rank.py corrects difficulty fit using the LLM's own read of the issue text).
LABELS_BY_EXPERIENCE = {
    "beginner": {
        "good first issue", "good-first-issue", "beginner", "easy",
        "help wanted", "documentation", "docs",
    },
    "intermediate": {"intermediate", "medium"},
    "advanced": {"advanced", "hard", "hard difficulty"},
}

ISSUE_CLOSING_PATTERN = re.compile(
    r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)",
    re.IGNORECASE,
)


# Issue numbers a PR body claims to close/fix/resolve.
def extract_linked_issue_numbers(pr_body: str | None) -> set[int]:
    if not pr_body:
        return set()
    return {int(match.group(2)) for match in ISSUE_CLOSING_PATTERN.finditer(pr_body)}


def _label_names(issue: dict) -> set[str]:
    return {
        (label["name"] if isinstance(label, dict) else label).lower()
        for label in issue.get("labels", [])
    }


def _is_assigned(issue: dict) -> bool:
    return bool(issue.get("assignees")) or bool(issue.get("assignee"))


def _matched_labels(issue: dict, experience_level: str) -> set[str]:
    return _label_names(issue) & LABELS_BY_EXPERIENCE.get(experience_level, set())


def updated_at(issue: dict) -> datetime:
    raw = issue.get("updated_at")
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


# Human-readable reasons this issue survived, fed to the scoring prompt
# (scoring_agent.py) as context for why it made the shortlist.
def _filter_reasons(issue: dict, matched_labels: set[str]) -> list[str]:
    reasons = []
    if matched_labels:
        reasons.append(f"label match: {', '.join(sorted(matched_labels))}")
    days_ago = (datetime.now(timezone.utc) - updated_at(issue)).days
    reasons.append(f"updated {days_ago} day{'s' if days_ago != 1 else ''} ago")
    reasons.append(f"{issue.get('comments', 0)} comment(s)")
    return reasons


# Returns the top N survivors as {"issue": ..., "filter_reasons": [...]} dicts.
def filter_candidates(
    issues: list[dict],
    pull_requests: list[dict],
    experience_level: str = "beginner",
    max_candidates: int = 15,
) -> list[dict]:
    linked_issue_numbers: set[int] = set()
    for pr in pull_requests:
        linked_issue_numbers |= extract_linked_issue_numbers(pr.get("body"))

    survivors = [
        issue
        for issue in issues
        if not _is_assigned(issue)
        and not issue.get("locked")
        and issue.get("number") not in linked_issue_numbers
    ]

    labeled = [(issue, _matched_labels(issue, experience_level)) for issue in survivors]

    # Sorting priority: label match, recency, then comments.
    def sort_key(pair: tuple[dict, set[str]]):
        issue, matched = pair
        return (
            -len(matched),
            -updated_at(issue).timestamp(),
            issue.get("comments", 0),
        )

    labeled.sort(key=sort_key)

    return [
        {"issue": issue, "filter_reasons": _filter_reasons(issue, matched)}
        for issue, matched in labeled[:max_candidates]
    ]
