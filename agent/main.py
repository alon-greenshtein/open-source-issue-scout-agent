import argparse
from dataclasses import dataclass

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
        help="Maximum number of candidate issues to analyze",
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


def main() -> None:
    config = build_config(parse_args())

    print("Open Source Issue Scout Agent")
    print(f"Owner: {config.owner}")
    print(f"Repository: {config.repo}")
    print(f"Experience level: {config.experience_level}")
    print(f"Max candidates: {config.max_candidates}")


if __name__ == "__main__":
    main()
