from agent.rank import rank_scores


def make_scored(
    number,
    recommended=True,
    difficulty="beginner",
    claim_status="unclaimed",
    clarity_score=5,
    updated_at="2024-01-01T00:00:00Z",
):
    return {
        "number": number,
        "recommended": recommended,
        "difficulty": difficulty,
        "claim_status": claim_status,
        "clarity_score": clarity_score,
        "updated_at": updated_at,
    }


def numbers(result):
    return [c["number"] for c in result]


def test_drops_non_recommended():
    scored = [make_scored(1, recommended=False), make_scored(2, recommended=True)]
    assert numbers(rank_scores(scored, "beginner")) == [2]


# --- difficulty fit, per experience level ---

def test_beginner_prefers_exact_then_easier_then_harder():
    scored = [
        make_scored(1, difficulty="advanced"),
        make_scored(2, difficulty="beginner"),
        make_scored(3, difficulty="intermediate"),
    ]
    assert numbers(rank_scores(scored, "beginner")) == [2, 3, 1]


def test_advanced_prefers_exact_then_easier_then_harder():
    scored = [
        make_scored(1, difficulty="beginner"),
        make_scored(2, difficulty="advanced"),
        make_scored(3, difficulty="intermediate"),
    ]
    assert numbers(rank_scores(scored, "advanced")) == [2, 3, 1]


def test_intermediate_prefers_exact_then_easier_then_harder():
    scored = [
        make_scored(1, difficulty="advanced"),
        make_scored(2, difficulty="beginner"),
        make_scored(3, difficulty="intermediate"),
    ]
    # intermediate exact, then easier (beginner), then harder (advanced)
    assert numbers(rank_scores(scored, "intermediate")) == [3, 2, 1]


# --- lower-priority tie-breakers ---

def test_unclaimed_before_possibly_claimed_when_difficulty_ties():
    scored = [
        make_scored(1, claim_status="possibly_claimed"),
        make_scored(2, claim_status="unclaimed"),
    ]
    assert numbers(rank_scores(scored, "beginner")) == [2, 1]


def test_clarity_breaks_ties_after_difficulty_and_claim():
    scored = [
        make_scored(1, clarity_score=6),
        make_scored(2, clarity_score=9),
    ]
    assert numbers(rank_scores(scored, "beginner")) == [2, 1]


def test_updated_at_is_last_tiebreaker():
    scored = [
        make_scored(1, updated_at="2024-01-01T00:00:00Z"),
        make_scored(2, updated_at="2024-06-01T00:00:00Z"),
    ]
    assert numbers(rank_scores(scored, "beginner")) == [2, 1]
