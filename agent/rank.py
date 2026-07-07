# Deterministic final ranking of scored candidates (no LLM involved).
#
# filter.py already did a cheap metadata-based pre-ranking to pick which
# issues were worth spending an LLM call on. That ordering is "spent" once
# the shortlist is chosen — this module produces a fresh, independent
# ordering of the issues the LLM actually recommended, using its richer
# judgments instead of the crude metadata proxies.
#
# Sort priority (lexicographic, most-significant first):
#   1. recommended == True   gate: non-recommended candidates are dropped
#   2. difficulty fit        exact match first; too-hard penalized more than
#                            too-easy (see DIFFICULTY_RANKS)
#   3. claim_status          unclaimed before possibly_claimed
#   4. clarity_score         higher first
#   5. updated_at            more recent first — the one filter signal with no
#                            LLM equivalent, kept as a marginal last tie-breaker

from agent.filter import updated_at

# For each experience_level, how good each issue difficulty is (0 = best).
# Deliberately NOT a symmetric distance: an issue harder than the user is
# ranked worse than one that's easier, because "too hard" can be an outright
# blocker while "too easy" is still doable (and a fine easy win).
DIFFICULTY_RANKS = {
    "beginner":     {"beginner": 0, "intermediate": 1, "advanced": 2},
    "intermediate": {"intermediate": 0, "beginner": 1, "advanced": 2},
    "advanced":     {"advanced": 0, "intermediate": 1, "beginner": 2},
}

CLAIM_RANKS = {"unclaimed": 0, "possibly_claimed": 1, "claimed": 2}

# Fallback rank for unexpected/missing values — sorts them to the bottom.
_WORST_RANK = 99


# Returns only the recommended candidates, ordered best-first.
# Each item is a merged dict: an IssueScore's fields plus the issue's
# number/title/url/updated_at (merged by the caller, since updated_at
# is not part of IssueScore).
def rank_scores(scored_candidates: list[dict], experience_level: str) -> list[dict]:
    difficulty_ranks = DIFFICULTY_RANKS.get(experience_level, {})
    recommended = [c for c in scored_candidates if c.get("recommended")]

    def sort_key(candidate: dict):
        return (
            difficulty_ranks.get(candidate.get("difficulty"), _WORST_RANK),
            CLAIM_RANKS.get(candidate.get("claim_status"), _WORST_RANK),
            -candidate.get("clarity_score", 0),
            -updated_at(candidate).timestamp(),
        )

    return sorted(recommended, key=sort_key)
