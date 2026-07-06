"""Markdown report generation from scored candidates.

Each candidate is expected to be a dict combining issue metadata with
scoring_agent.py's output: number, title, url, clarity_score, difficulty,
likely_files, already_handled, handled_reason, value_explanation, recommended.
This is the contract scoring_agent.py needs to produce.
"""


def generate_markdown_report(
    owner: str,
    repo: str,
    scored_candidates: list[dict],
    top_n: int = 5,
) -> str:
    """Top-N recommended candidates as a Markdown report."""
    recommended = [c for c in scored_candidates if c.get("recommended")]
    recommended.sort(key=lambda c: c.get("clarity_score", 0), reverse=True)
    top = recommended[:top_n]

    lines = [f"# Contribution opportunities in {owner}/{repo}", ""]

    if not top:
        lines.append("No strong candidates found in this pass.")
        return "\n".join(lines)

    for rank, candidate in enumerate(top, start=1):
        lines.append(f"## {rank}. #{candidate['number']} — {candidate['title']}")
        lines.append("")
        lines.append(f"- **Difficulty**: {candidate.get('difficulty', 'unknown')}")
        lines.append(f"- **Clarity score**: {candidate.get('clarity_score', 'n/a')}/10")

        likely_files = candidate.get("likely_files") or []
        if likely_files:
            lines.append(f"- **Likely files affected**: {', '.join(likely_files)}")

        if candidate.get("already_handled"):
            lines.append(f"- **Already being handled**: {candidate.get('handled_reason', 'yes')}")

        if candidate.get("url"):
            lines.append(f"- **Link**: {candidate['url']}")

        lines.append("")
        lines.append(candidate.get("value_explanation", ""))
        lines.append("")

    return "\n".join(lines)
