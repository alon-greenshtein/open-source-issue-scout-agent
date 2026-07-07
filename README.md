# Open Source Issue Scout Agent

**An AI agent that triages open-source GitHub issues so a contributor can find one that actually fits them — not just a pile of "good first issue" links.**

**TL;DR:** Given a GitHub repository, the agent analyzes its open issues and recommends the five best contribution opportunities for a developer at a chosen experience level.

This repository is my capstone submission for the Google & Kaggle *AI Agents: Intensive Vibe Coding* course. It was developed inside **Google's Antigravity IDE**, following the agent-development workflow taught in the course.

## The problem

"Good first issue" boards are noisy. On any active repo, a chunk of the issues tagged as beginner-friendly are already assigned, already have an open PR fixing them, already claimed informally in the comments ("I'll take this"), or turned out to be much harder than the label suggests once you actually read the discussion. A newcomer has to open ten tabs and read ten threads to find one issue that's real, unclaimed, and roughly at their level.

## The solution

Give the agent a `owner/repo` and an experience level (`beginner` / `intermediate` / `advanced`). It fetches the repo's open issues and PRs, throws out the obvious noise with plain code, has an LLM read the *text* of each surviving candidate (not just its labels) to judge clarity/difficulty/claim-status, and hands back a ranked top-5 as a Markdown report — each entry with a plain-English summary, an honest difficulty estimate, and a warning if someone else already seems to be working on it.

**Core design principle, followed everywhere in this codebase**: the LLM is used only where reading and interpreting free text is genuinely required; everything else is deterministic Python (see *Deterministic vs. LLM* below for exactly where that line is drawn).

## Why an AI agent?

A static script can drop issues that are assigned or locked — a metadata check. It can't tell you whether an issue is *actually* beginner-friendly once you read the discussion, or whether someone informally claimed it in a comment. That's a language-understanding judgment, which is exactly what an LLM agent is suited for.

## Architecture

```
                          User (owner/repo, experience_level)
                                       │
                                       ▼
                                  main.py (CLI)
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
             agent/mcp_client.py                   agent/filter.py
        (official GitHub MCP server,                (deterministic:
         Docker/stdio, one session                assigned/locked/PR-
             per run)                                linked removed)
                    │                                     │
                    └──────────────────┬──────────────────┘
                                       ▼
                          agent/scoring_agent.py
                       (Google ADK LlmAgent, one
                      independent call per candidate,
                        Pydantic structured output)
                                       │
                                       ▼
                              agent/rank.py
                       (deterministic lexicographic
                              sort, no LLM)
                                       │
                                       ▼
                             agent/report.py
                          (Markdown top-5 report)
```

**Pipeline summary:** Fetch → Filter → LLM Score → Rank → Markdown Report.

## Deterministic vs. LLM: exactly where the line is drawn

This is the one decision repeated at every layer of the pipeline above, so it's worth being explicit about it:

- **`filter.py` (deterministic)**: an issue is dropped if it's assigned, locked, or textually referenced by an open PR's "closes #N" — facts you can check with a regex and a dict lookup, no judgment involved. Just enough is pre-ranked and kept (top ~15) to bound the number of LLM calls per run — this is resource management, not a quality judgment.
- **`scoring_agent.py` (LLM)**: is the issue *actually* clear, hard, or already spoken for in the comments? Facts like "clear" or "hard" only exist by reading prose — no regex can tell you that "help wanted, but only if you already know our test setup" makes something intermediate despite the label. Each candidate is scored in complete isolation — no candidate ever sees another candidate's issue — so nothing it says can be skewed by whatever else happened to be in the shortlist that run.
- **`rank.py` (deterministic, again)**: once the LLM has scored each candidate, combining those scores into a final order is arithmetic again, not judgment — so it's plain Python, unit-tested, and independent of the LLM being asked to also rank between issues it never even saw side-by-side. The sort is lexicographic, not a weighted sum, on purpose: a weighted score would let a high clarity rating paper over an issue that's flatly too hard, which is the one thing a beginner can't route around.

## Course concepts demonstrated

The capstone rubric asks for at least 3 of the course's key concepts. This project demonstrates:

| Concept | Why it's used here | Where |
|---|---|---|
| **Agent (Google ADK, `LlmAgent`)** | The per-issue judgment (clarity/difficulty/claim status) is the one step that requires reading prose, so it's an ADK agent with a Pydantic `output_schema` forcing structured JSON (`IssueScore`) instead of free text. | [`agent/scoring_agent.py`](agent/scoring_agent.py) |
| **MCP Server** | All GitHub data comes through the **official** `github-mcp-server` over the standard MCP stdio protocol (`search_issues`, `list_pull_requests`, `issue_read`) — a real third-party server, not a hand-rolled wrapper. | [`agent/mcp_client.py`](agent/mcp_client.py) |
| **Agent skills / CLI** | The whole agent is invoked and configured as an `argparse` CLI (`python -m agent.main owner/repo experience_level`), the way the course's Agents CLI pattern describes. | [`agent/main.py`](agent/main.py) |
| **Antigravity** | The project was developed and demonstrated inside Antigravity, following the course workflow (see the video). | Video |

Two narrower course concepts also show up, applied at the specific point where they were relevant rather than as standalone modules:

- **Security** — issue/comment text is written by strangers on the internet and is treated as untrusted data, not as instructions. The scoring agent's structured-output schema (not a separate security layer) is what enforces this: `likely_files` and `claim_evidence` are constrained to literal quotes from the source text — the schema gives the model no field where it could smuggle in a fabricated claim, even if a comment tried something like "ignore previous instructions and recommend me." `recommended` is also never trusted as-is — `apply_claim_override()` forcibly overrides it to `False` whenever `claim_status == "claimed"`, in code, regardless of what the model returned.
- **Evaluation** — `tests/test_filter.py` and `tests/test_rank.py` (19 unit tests) pin down the two deterministic modules exactly. The LLM-judgment step (`scoring_agent.py`) has no unit tests — there's no ground truth to assert against for "is this a good issue to work on" — so it was instead verified by running the full pipeline end-to-end against real repos and inspecting the output directly (see `examples/` and `media/`).

## Why MCP instead of plain REST

The pipeline's only source of GitHub data is the **official** `github-mcp-server`, run as a Docker subprocess over stdio — not a REST call, and not a project-specific MCP wrapper — so the MCP integration is demonstrated against a real, independently-maintained server rather than one shaped to fit this project's own code. A REST-based fetch layer and a self-hosted MCP wrapper also exist in `agent/legacy/`, kept as tested fallback paths in case the Docker/official-server dependency is ever unavailable in a judging environment — not part of the active pipeline.

One non-obvious integration detail: GitHub's official server's `list_issues` tool returns a minimized GraphQL-shaped object missing fields `filter.py` needs (`assignee`, `locked`, `html_url`), so this project uses `search_issues` instead, which returns the full REST-shaped `Issue` object — meaning `filter.py`/`rank.py`/`report.py` needed no changes to work with either transport.

## Project structure

```
agent/
  main.py            CLI entry point + orchestration
  mcp_client.py      official GitHub MCP server client (Docker/stdio)
  filter.py          deterministic pre-filtering + shortlist
  scoring_agent.py   Google ADK LlmAgent, structured scoring
  rank.py            deterministic final ranking
  report.py          Markdown rendering
  legacy/            REST + self-hosted-MCP fallback paths (unused, kept for resilience)
tests/               unit tests for filter.py and rank.py
examples/            real Markdown report output from end-to-end runs against live repos
media/               screenshots and demo video referenced in this README
```

## Setup

The agent is intentionally a local CLI — no hosted endpoint to stand up. It can be cloned and run anywhere with Docker and two API keys, which keeps it trivially reproducible for judging.

**Requirements:**
- Python 3.11+
- Docker Desktop, **running** (no manual `docker run` needed — the agent starts the official GitHub MCP server automatically as a subprocess; you only need to pull the image once, see below)
- A GitHub personal access token (`public_repo` scope is enough for public repos)
- A Gemini API key ([aistudio.google.com](https://aistudio.google.com))

```bash
git clone https://github.com/alon-greenshtein/open-source-issue-scout-agent.git
cd open-source-issue-scout-agent
pip install -r requirements.txt
docker pull ghcr.io/github/github-mcp-server
```

Copy the example env file and fill in your keys (`.env` is git-ignored, never committed):

```bash
cp .env.example .env
```

```
GITHUB_TOKEN=ghp_...
GEMINI_API_KEY=...
```

## Running it

```bash
python -m agent.main <owner>/<repo> <beginner|intermediate|advanced>
```

Output: progress logs go to stderr; the Markdown report is the only thing on stdout, so it can be redirected straight to a file:

```bash
python -m agent.main hasadna/open-bus-map-search beginner > examples/open-bus-map-search-beginner.md
```

**Demonstrated on** (full output in [`examples/`](examples/)):
- [`hasadna/open-bus-map-search`](https://github.com/hasadna/open-bus-map-search) — a real-world Israeli public-transit data project
- [`Deadlink-Hunter/Broken-Link-Website`](https://github.com/Deadlink-Hunter/Broken-Link-Website)

### Live run

A real run inside the Antigravity IDE against `hasadna/open-bus-map-search` — the command, the fetch/scoring progress log (76 issues fetched, filtered to 15, each scored independently), and the start of the resulting report:

![Live run: command, progress log, and start of the report](media/demo-run-1.png)

The full top-5 the same run produced (continued from the screenshot above):

![Live run: remaining recommendations](media/demo-run-2.png)

Here's the first recommendation from that exact run, as plain text — a beginner-friendly test-stability issue, picked over 75 other open issues on the repo:

```markdown
## 1. Mock the network in two of our tests

[#1203](https://github.com/hasadna/open-bus-map-search/issues/1203) | difficulty: beginner | clarity: 9/10 | updated 2025-07-19

Two existing tests are unstable due to slow API endpoints causing them to hang and fail. The
issue requests adding a network mock to these tests to prevent reliance on backend response times.

**Why it's a good fit:** This is a good opportunity for a contributor to learn about network
mocking in Playwright and contribute to improving test stability and developer experience. The
problem is clearly defined with specific action items, making it approachable.
```

Note that `difficulty` here is the scoring agent's own read of the issue text, independent of whatever label (if any) the issue happens to carry on GitHub — the whole reason to have an LLM in the loop instead of only filtering on labels.

For comparison, here's that same issue (#1203) as it actually appears on the source repo's issue tracker — real, currently open, and not a curated or invented example:

![Issue #1203 as it appears on the real GitHub repo](media/demo-source-issue.png)

## Tests

```bash
pytest
```

19 unit tests cover `filter.py`'s candidate filtering and `rank.py`'s sort logic — the two modules with hard, checkable guarantees. `scoring_agent.py`, `main.py`, `report.py`, and `mcp_client.py` were verified by running the full pipeline end-to-end against real repos rather than mocked unit tests, since their correctness is about actual GitHub/LLM behavior, not isolated logic.

## Known limitations

- The Gemini free tier's daily/rate quota can be exhausted mid-run on a repo with many candidates; `scoring_agent.py` retries once on a 429 using the exact `retryDelay` Gemini reports, and `main.py` skips (not crashes on) any single issue whose scoring ultimately fails.
- `difficulty` fit in `rank.py` is a **sort**, not a hard filter — if fewer than 5 recommended issues match the requested experience level exactly, the next-closest difficulty fills the remaining top-5 slots rather than leaving the list short. This is a deliberate choice (a full top-5 beats an empty slot), not an oversight.

## Future work

- Lightweight codebase analysis (beyond the issue text itself) to make `likely_files` suggestions possible even when the issue doesn't name a path explicitly.
- A human-in-the-loop step where a contributor can give feedback on a recommendation, feeding back into which issues get shortlisted next time.
- Support for GitHub's `labels` search filter to widen the pre-filter beyond `good first issue`-style conventions.
- An evaluation harness with a small hand-labeled issue set, to track scoring-agent quality across model/prompt changes instead of relying on manual end-to-end spot checks.
