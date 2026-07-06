from agent.filter import extract_linked_issue_numbers, filter_candidates


def make_issue(
    number,
    labels=None,
    comments=0,
    updated_at="2024-01-01T00:00:00Z",
    assignees=None,
    assignee=None,
    locked=False,
):
    return {
        "number": number,
        "title": f"Issue {number}",
        "labels": labels or [],
        "comments": comments,
        "updated_at": updated_at,
        "assignees": assignees or [],
        "assignee": assignee,
        "locked": locked,
    }


def make_pr(body):
    return {"body": body}


# --- extract_linked_issue_numbers ---

def test_extract_linked_issue_numbers_matches_common_keywords():
    assert extract_linked_issue_numbers("This closes #12") == {12}
    assert extract_linked_issue_numbers("Fixes #34 and fixes #35") == {34, 35}
    assert extract_linked_issue_numbers("resolve #5") == {5}


def test_extract_linked_issue_numbers_case_insensitive():
    assert extract_linked_issue_numbers("CLOSES #7") == {7}


def test_extract_linked_issue_numbers_empty_for_no_match_or_none():
    assert extract_linked_issue_numbers("just a regular PR description") == set()
    assert extract_linked_issue_numbers(None) == set()


# --- filter_candidates ---

def test_excludes_assigned_issues():
    issues = [
        make_issue(1, assignees=[{"login": "someone"}]),
        make_issue(2),
    ]
    result = filter_candidates(issues, [])
    numbers = {c["issue"]["number"] for c in result}
    assert numbers == {2}


def test_excludes_issues_with_legacy_assignee_field():
    issues = [
        make_issue(1, assignee={"login": "someone"}),
        make_issue(2),
    ]
    result = filter_candidates(issues, [])
    numbers = {c["issue"]["number"] for c in result}
    assert numbers == {2}


def test_excludes_locked_issues():
    issues = [
        make_issue(1, locked=True),
        make_issue(2),
    ]
    result = filter_candidates(issues, [])
    numbers = {c["issue"]["number"] for c in result}
    assert numbers == {2}


def test_excludes_issues_already_linked_to_open_pr():
    issues = [make_issue(1), make_issue(2)]
    pull_requests = [make_pr("This PR closes #1")]
    result = filter_candidates(issues, pull_requests)
    numbers = {c["issue"]["number"] for c in result}
    assert numbers == {2}


def test_ranks_matching_label_above_non_matching():
    issues = [
        make_issue(1, labels=["enhancement"]),
        make_issue(2, labels=["good first issue"]),
    ]
    result = filter_candidates(issues, [], experience_level="beginner")
    assert [c["issue"]["number"] for c in result] == [2, 1]


def test_respects_max_candidates_cap():
    issues = [make_issue(i) for i in range(10)]
    result = filter_candidates(issues, [], max_candidates=3)
    assert len(result) == 3


def test_filter_reasons_reflect_label_match():
    issues = [make_issue(1, labels=["good first issue"], comments=4)]
    result = filter_candidates(issues, [], experience_level="beginner")
    reasons = result[0]["filter_reasons"]
    assert any("good first issue" in reason for reason in reasons)
    assert any("4 comment" in reason for reason in reasons)


def test_ranks_more_recently_updated_above_older_when_labels_tie():
    issues = [
        make_issue(1, updated_at="2024-01-01T00:00:00Z"),
        make_issue(2, updated_at="2024-06-01T00:00:00Z"),
    ]
    result = filter_candidates(issues, [])
    assert [c["issue"]["number"] for c in result] == [2, 1]


def test_comments_only_break_ties_when_labels_and_recency_are_equal():
    same_date = "2024-01-01T00:00:00Z"
    issues = [
        make_issue(1, updated_at=same_date, comments=10),
        make_issue(2, updated_at=same_date, comments=2),
    ]
    result = filter_candidates(issues, [])
    assert [c["issue"]["number"] for c in result] == [2, 1]
