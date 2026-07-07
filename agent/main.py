import argparse
import sys
from dataclasses import dataclass

from agent.fetch import get_issue_comments, get_open_issues, get_open_pull_requests
from agent.filter import filter_candidates
from agent.rank import rank_scores
from agent.report import generate_markdown_report
from agent.scoring_agent import score_candidate

VALID_LEVELS = {"beginner", "intermediate", "advanced"}


@dataclass
class Config:
    owner: str
    repo: str
    experience_level: str
    max_candidates: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open Source Issue Scout Agent")

    parser.add_argument(
        "repo",
        help="GitHub repository in owner/repo format, for example: microsoft/TypeScript",
    )
    parser.add_argument(
        "experience_level",
        choices=sorted(VALID_LEVELS),
        help="User experience level",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=15,
        help="Maximum number of candidate issues to score with the LLM",
    )

    return parser.parse_args()


def build_config(args: argparse.Namespace) -> Config:
    parts = args.repo.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("Repository must be in owner/repo format (owner/repo)")

    owner, repo = parts
    return Config(
        owner=owner,
        repo=repo,
        experience_level=args.experience_level,
        max_candidates=args.max_candidates,
    )


# Progress goes to stderr so stdout stays clean (just the Markdown report),
# which lets the report be piped to a file: `... beginner > report.md`.
def _log(message: str) -> None:
    print(message, file=sys.stderr)


# Flattens one filtered candidate + its LLM score into the single merged dict
# that rank_scores/report expect. GitHub's web link is html_url ("url" is the
# API endpoint), so it's mapped to "url" here.
def _merge(candidate: dict, score) -> dict:
    issue = candidate["issue"]
    return {
        "number": issue["number"],
        "title": issue["title"],
        "url": issue.get("html_url", ""),
        "updated_at": issue.get("updated_at"),
        **score.model_dump(),
    }


# Fetches comments and scores each candidate one at a time (network + LLM
# call per issue, so each gets its own progress log and try/except — one
# bad issue shouldn't sink the whole run). Returns merged dicts, ready for
# rank_scores/report.
def _score_candidates(config: Config, candidates: list[dict]) -> list[dict]:
    scored = []
    for index, candidate in enumerate(candidates, start=1):
        number = candidate["issue"]["number"]
        _log(f"  scoring {index}/{len(candidates)}: #{number}")
        comments = get_issue_comments(config.owner, config.repo, number)
        try:
            score = score_candidate(candidate, comments, config.experience_level)
        except Exception as exc:
            _log(f"    ! skipped #{number}: {exc}")
            continue
        scored.append(_merge(candidate, score))
    return scored


# The full agent pipeline: fetch -> filter -> score (per candidate) -> rank
# -> report. Deterministic filtering/ranking bracket the single LLM step in
# the middle; nothing here re-implements logic that lives in those modules.
def scout(config: Config) -> str:
    _log(f"Fetching open issues and PRs for {config.owner}/{config.repo}...")
    issues = get_open_issues(config.owner, config.repo)
    pull_requests = get_open_pull_requests(config.owner, config.repo)
    _log(f"  {len(issues)} open issues, {len(pull_requests)} open PRs.")

    candidates = filter_candidates(issues, pull_requests, config.experience_level, config.max_candidates)
    _log(f"Filtered to {len(candidates)} candidate(s); scoring with the LLM...")

    scored = _score_candidates(config, candidates)
    ranked = rank_scores(scored, config.experience_level)
    return generate_markdown_report(config.owner, config.repo, ranked)


def main() -> None:
    config = build_config(parse_args())
    print(scout(config))


if __name__ == "__main__":
    main()
