# LLM judgment step: scores a single pre-filtered candidate issue.
#
# IssueScore only carries the fields that require LLM judgment. Identity
# fields (number, title, url) live on the issue dict already produced by
# fetch.py/filter.py — the caller merges the two before handing a row to
# report.py, so this schema doesn't duplicate data the LLM has no reason
# to re-generate.

import asyncio
import sys
import time
import uuid
from typing import Literal

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.genai.errors import ClientError
from pydantic import BaseModel, Field

load_dotenv()

APP_NAME = "issue_scout"
USER_ID = "cli_user"

# Model name is swappable.
SCORING_MODEL = "gemini-2.5-flash"

# Long issue threads get truncated to the most recent comments before being
# sent to the model — keeps context/cost bounded on popular repos.
MAX_COMMENTS = 20

SCORING_INSTRUCTION = """
You evaluate a single GitHub issue to help a contributor decide whether it's
worth picking up. You will receive the issue title/body, its labels and why
it survived pre-filtering, its full comment thread, and the contributor's
experience_level (beginner/intermediate/advanced).

General rules:
- Do not invent information not present in the issue or comments.
- likely_files and claim_evidence are the two fields where this matters most:
  likely_files must only name a path that is explicitly written in the issue/
  comments (empty list if none — never guess from general project knowledge),
  and claim_evidence must be a literal quote from a comment, not a paraphrase
  that makes the claim sound stronger or weaker than what was actually said.

See each field's own description below for what it specifically expects.
""".strip()


class IssueScore(BaseModel):
    clarity_score: int = Field(
        ge=1, le=10,
        description="How clearly the issue describes the problem and expected outcome.",
    )
    difficulty: Literal["beginner", "intermediate", "advanced"] = Field(
        description="Estimated difficulty to implement a fix, independent of the requester's experience_level.",
    )
    likely_files: list[str] = Field(
        default_factory=list,
        description=(
            "File or directory paths, but ONLY if explicitly named in the issue "
            "title/body/comments (e.g. a backtick-quoted path, a stack trace line, "
            "or a maintainer saying 'this happens in X'). Do not guess or infer paths "
            "from general domain knowledge of the project. Empty list if none are named."
        ),
    )
    claim_status: Literal["unclaimed", "possibly_claimed", "claimed"] = Field(
        description=(
            "Whether someone else has already claimed this issue, based only on the "
            "comment thread (filter.py already excludes issues linked to an open PR, "
            "so this is about informal signals in comments, not PR links). "
            "'claimed': explicit evidence someone is actively working on it or has a fix "
            "ready (e.g. 'I'm working on this', 'PR incoming'). "
            "'possibly_claimed': a weak/ambiguous signal only (e.g. 'I'll take a look "
            "tomorrow', a stated intent with no confirmation of actual progress). "
            "'unclaimed': no such signal at all."
        ),
    )
    claim_evidence: str | None = Field(
        default=None,
        description=(
            "A short literal quote from the comment that justifies claim_status. "
            "Quote the actual words, don't paraphrase into a stronger or weaker claim "
            "than what was said. Null when claim_status is 'unclaimed'."
        ),
    )
    problem_summary: str = Field(
        description=(
            "1-2 neutral sentences summarizing only what the issue asks for or what "
            "problem is reported — not whether it's a good opportunity, not difficulty, "
            "not a recommendation. If the issue itself is unclear about what's being "
            "asked, say that briefly instead of guessing what it might mean."
        ),
    )
    value_explanation: str = Field(
        description=(
            "1-3 sentences on why this is (or isn't) a good contribution opportunity. "
            "If the issue/discussion is too thin or ambiguous to judge confidently, say so here."
        ),
    )
    recommended: bool = Field(
        description=(
            "True if this is a legitimate candidate worth surfacing to the contributor, "
            "after weighing clarity, difficulty, claim_status, and discussion quality."
        ),
    )


scoring_agent = LlmAgent(
    name="issue_scoring_agent",
    model=SCORING_MODEL,
    instruction=SCORING_INSTRUCTION,
    output_schema=IssueScore,
)


# Builds the plain-text prompt sent to scoring_agent: issue body, why it
# survived pre-filtering, and its (possibly truncated) comment thread.
def _build_input_text(candidate: dict, comments: list[dict], experience_level: str) -> str:
    issue = candidate["issue"]
    recent_comments = comments[-MAX_COMMENTS:]
    comment_text = "\n\n".join(
        f"Comment by {c.get('user', {}).get('login', 'unknown')}:\n{c.get('body', '')}"
        for c in recent_comments
    ) or "(no comments)"
    filter_reasons = ", ".join(candidate.get("filter_reasons", [])) or "n/a"

    return f"""
Contributor experience_level: {experience_level}

Issue #{issue['number']}: {issue['title']}

Body:
{issue.get('body') or '(no body)'}

Why this issue survived pre-filtering: {filter_reasons}

Comments:
{comment_text}
""".strip()


# A claimed issue is never recommended, regardless of what the LLM itself
# put in `recommended` — enforced in code, not trusted to the model's own
# internal consistency.
def apply_claim_override(score: IssueScore) -> IssueScore:
    if score.claim_status == "claimed" and score.recommended:
        return score.model_copy(update={"recommended": False})
    return score


# Gemini's own 429 response tells us exactly how long to wait (RetryInfo.
# retryDelay, e.g. "50s") — parsed here instead of guessing a backoff curve.
def _retry_delay_seconds(error: ClientError) -> float | None:
    details = (error.details or {}).get("error", {}).get("details", [])
    for detail in details:
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            raw = detail.get("retryDelay", "")
            if raw.endswith("s"):
                try:
                    return float(raw[:-1])
                except ValueError:
                    return None
    return None


# ADK-specific plumbing: run the agent for one message and pull the final
# response text out of its event stream. Isolated here so score_candidate()
# reads as plain business logic, and so an ADK API change only touches this
# one function.
#
# Retries only on 429 (rate/quota limit), since that's the one failure mode
# where waiting and resending the same request is expected to succeed.
def _run_agent(session_id: str, message: types.Content, max_retries: int = 2) -> str:
    session_service = InMemorySessionService()
    asyncio.run(
        session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
    )
    runner = Runner(agent=scoring_agent, app_name=APP_NAME, session_service=session_service)

    for attempt in range(max_retries + 1):
        try:
            for event in runner.run(user_id=USER_ID, session_id=session_id, new_message=message):
                if event.is_final_response() and event.content and event.content.parts:
                    return event.content.parts[0].text
            raise RuntimeError("scoring_agent produced no final response")
        except ClientError as error:
            if error.code != 429 or attempt == max_retries:
                raise
            delay = _retry_delay_seconds(error) or 5
            print(f"    rate limit hit; retrying in {delay}s...", file=sys.stderr)
            time.sleep(delay)


# Scores one filter_candidates() row given its full comment thread.
# candidate: {"issue": <issue dict from fetch.py>, "filter_reasons": [...]}
# comments: fetch.get_issue_comments() output for this issue's number
def score_candidate(candidate: dict, comments: list[dict], experience_level: str) -> IssueScore:
    message = types.Content(
        role="user",
        parts=[types.Part(text=_build_input_text(candidate, comments, experience_level))],
    )
    json_text = _run_agent(session_id=str(uuid.uuid4()), message=message)
    return apply_claim_override(IssueScore.model_validate_json(json_text))
