# Markdown report generation from ranked candidates.
#
# Input is the output of rank.rank_scores(): a list already filtered to
# recommended issues and ordered best-first. This module does NOT sort or
# re-filter — it only slices the top N and renders them. Each item is a
# merged dict carrying both issue metadata (number, title, url, updated_at)
# and the LLM's IssueScore fields (problem_summary, difficulty, clarity_score,
# claim_status, claim_evidence, likely_files, value_explanation).
#
# Deliberately NOT displayed:
#   - recommended: every item here is already recommended (it was the upstream
#     gate), so printing it on each row is noise.
#   - filter_reasons and labels: internal pre-filtering plumbing, not useful
#     to a contributor deciding what to work on.


# A short warning line about who may already be on the issue, or None when
# it's unclaimed (absence of a warning is itself the "it's free" signal).
def _claim_note(candidate: dict) -> str | None:
    status = candidate.get("claim_status")
    if status == "possibly_claimed":
        evidence = candidate.get("claim_evidence")
        quote = f': "{evidence}"' if evidence else ""
        return f"**Possibly already being worked on**{quote}"
    if status == "claimed":
        # Shouldn't reach here in the normal pipeline — scoring_agent's
        # apply_claim_override forces recommended=False for "claimed", and
        # rank_scores filters to recommended=True only. Kept anyway because
        # report.py doesn't own or enforce that invariant itself; if it's
        # ever called with unfiltered data, staying silent here would mean
        # showing a claimed issue as if it were free — the one failure mode
        # this whole claim_status design exists to prevent.
        return "**Already claimed** — likely not available."
    return None


# Renders one ranked issue as a Markdown block.
def _render_candidate(rank: int, candidate: dict) -> list[str]:
    number = candidate["number"]
    url = candidate.get("url", "")

    meta = [f"[#{number}]({url})" if url else f"#{number}"]
    meta.append(f"difficulty: {candidate.get('difficulty', 'unknown')}")
    if candidate.get("clarity_score") is not None:
        meta.append(f"clarity: {candidate['clarity_score']}/10")
    if candidate.get("updated_at"):
        meta.append(f"updated {candidate['updated_at'][:10]}")

    lines = [f"## {rank}. {candidate['title']}", "", " | ".join(meta), ""]

    if candidate.get("problem_summary"):
        lines += [candidate["problem_summary"], ""]

    claim_note = _claim_note(candidate)
    if claim_note:
        lines += [claim_note, ""]

    likely_files = candidate.get("likely_files") or []
    if likely_files:
        formatted = ", ".join(f"`{path}`" for path in likely_files)
        lines += [f"**Where to look:** {formatted}", ""]

    if candidate.get("value_explanation"):
        lines += [f"**Why it's a good fit:** {candidate['value_explanation']}", ""]

    return lines


# Builds the top-N Markdown report from an already-ranked candidate list.
def generate_markdown_report(
    owner: str,
    repo: str,
    ranked_candidates: list[dict],
    top_n: int = 5,
) -> str:
    top = ranked_candidates[:top_n]

    lines = [f"# Contribution opportunities in {owner}/{repo}", ""]
    if not top:
        lines.append("No strong candidates found in this pass.")
        return "\n".join(lines)

    for rank, candidate in enumerate(top, start=1):
        lines += _render_candidate(rank, candidate)

    return "\n".join(lines).rstrip() + "\n"
