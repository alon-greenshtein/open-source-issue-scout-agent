# MCP client: talks to the official GitHub MCP server
# (ghcr.io/github/github-mcp-server, run as a Docker subprocess over stdio)
# and exposes the same three functions as fetch.py with the same signatures,
# so main.py stays agnostic to how the data is fetched.
#
# Why this shape: the project's course requirement is to use MCP. Rather than
# wrap our own REST code in a home-grown MCP server (that path still exists —
# see agent/legacy/mcp_server.py — and is the level-2 fallback in ROLLBACK.md),
# the client here speaks to GitHub's real MCP server. The server returns issue/PR
# JSON in the same field shape as GitHub's REST API (verified live), so the
# deterministic pipeline below it (filter.py, rank.py, report.py) is unchanged.
#
# Tool mapping (fetch.py -> official MCP tool):
#   get_open_issues         -> search_issues   (query "is:issue is:open no:assignee")
#   get_open_pull_requests  -> list_pull_requests
#   get_issue_comments      -> issue_read (method="get_comments")
#
# Why the threading machinery: the MCP client SDK is async and a session owns
# a live subprocess (the Docker container) plus background stream tasks that
# must stay alive between calls. One scout() run makes several search/list
# pages plus up to 15 comment fetches, so we keep ONE session (one container)
# open for the whole run: a dedicated asyncio loop runs in a background thread
# and each tool call is dispatched onto it. The session is created lazily on
# first use and torn down once via close_mcp_client().

import asyncio
import concurrent.futures
import json
import os
import threading
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

# GitHub's official MCP server image. The container reads its token from the
# GITHUB_PERSONAL_ACCESS_TOKEN env var; we forward this project's existing
# GITHUB_TOKEN (from .env) into the container via `docker run -e`.
_IMAGE = "ghcr.io/github/github-mcp-server"
_SERVER_PARAMS = StdioServerParameters(
    command="docker",
    args=["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", _IMAGE],
    env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
)

# GitHub's list/search endpoints cap at 100 results per page.
_PER_PAGE = 100


# Every tool here returns its payload as a JSON string in the first content
# block (structuredContent is unused by this server), so parse that. Raises a
# clear error on tool failure instead of letting a non-JSON error message hit
# json.loads and surface as a confusing JSONDecodeError.
def _payload(result):
    if result.isError:
        text = result.content[0].text if result.content else "(no error detail)"
        raise RuntimeError(f"MCP tool call failed: {text}")
    if result.content:
        return json.loads(result.content[0].text)
    return None


# Owns the background event loop and the single long-lived MCP session.
#
# The MCP session is built on anyio task groups whose cancel scopes must be
# entered AND exited in the same asyncio task. So we can't just fire each tool
# call (and the final close) as a separate run_coroutine_threadsafe coroutine —
# each of those runs in its own task, and closing the session from a different
# task than the one that opened it raises "Attempted to exit cancel scope in a
# different task". Instead, one long-lived _serve() coroutine owns the whole
# session lifecycle: it opens the session, then services tool calls off a queue,
# and closes the session on shutdown — all within that single task.
class _MCPBridge:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        # (name, arguments, future) requests; None is the shutdown sentinel.
        self._queue: asyncio.Queue = asyncio.run_coroutine_threadsafe(
            self._make_queue(), self._loop
        ).result()
        self._serving = asyncio.run_coroutine_threadsafe(self._serve(), self._loop)

    async def _make_queue(self) -> asyncio.Queue:
        return asyncio.Queue()

    # The single task that owns the session: opens it, services requests until
    # the shutdown sentinel, then closes it — enter and exit in the same task.
    async def _serve(self) -> None:
        async with AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(stdio_client(_SERVER_PARAMS))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            while True:
                request = await self._queue.get()
                if request is None:
                    return
                name, arguments, future = request
                try:
                    result = await session.call_tool(name, arguments)
                    self._loop.call_soon_threadsafe(future.set_result, _payload(result))
                except Exception as exc:
                    self._loop.call_soon_threadsafe(future.set_exception, exc)

    # Enqueues a tool call and blocks the calling (sync) thread for its result.
    def call(self, name: str, arguments: dict):
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (name, arguments, future))
        return future.result()

    def close(self) -> None:
        # Signal _serve() to close the session (in its own task), wait for it to
        # finish, then stop the loop.
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        self._serving.result()
        self._loop.call_soon_threadsafe(self._loop.stop)


_bridge: _MCPBridge | None = None


def _get_bridge() -> _MCPBridge:
    global _bridge
    if _bridge is None:
        _bridge = _MCPBridge()
    return _bridge


# Page through a tool the same way fetch.py's _paginated_get did: fetch pages
# of _PER_PAGE until a partial/empty page (the end) or, if max_items is set,
# until we have enough (then trim). `extract` pulls the list out of one page's
# payload — the identity for tools that return a bare JSON array, or ["items"]
# for search_issues, which wraps its results in an object.
def _paginate(tool: str, base_args: dict, extract, max_items: int | None) -> list[dict]:
    results: list[dict] = []
    page = 1
    while True:
        payload = _get_bridge().call(tool, {**base_args, "page": page, "perPage": _PER_PAGE})
        page_items = extract(payload) if payload is not None else []
        if not page_items:
            break
        results.extend(page_items)
        if max_items is not None and len(results) >= max_items:
            return results[:max_items]
        if len(page_items) < _PER_PAGE:
            break
        page += 1
    return results


# The three public functions below mirror fetch.py's signatures exactly.
#
# search_issues sorts by "updated" and scopes with "no:assignee" so assigned
# issues are dropped server-side (filter.py still drops locked ones, since the
# `locked` field is present in the results). max_issues caps the result the
# same way fetch.py's cap did.
def get_open_issues(owner: str, repo: str, max_issues: int = 300) -> list[dict]:
    base = {
        "query": f"repo:{owner}/{repo} is:issue is:open no:assignee",
        "sort": "updated",
        "order": "desc",
    }
    return _paginate("search_issues", base, lambda payload: payload.get("items", []), max_issues)


def get_open_pull_requests(owner: str, repo: str, max_prs: int = 100) -> list[dict]:
    base = {"owner": owner, "repo": repo, "state": "open", "sort": "updated", "direction": "desc"}
    return _paginate("list_pull_requests", base, lambda payload: payload, max_prs)


# No cap: the full thread is fetched, then scoring_agent.py truncates to the
# most recent MAX_COMMENTS — so all pages are needed to get the true "recent".
def get_issue_comments(owner: str, repo: str, issue_number: int) -> list[dict]:
    base = {"method": "get_comments", "owner": owner, "repo": repo, "issue_number": issue_number}
    return _paginate("issue_read", base, lambda payload: payload, None)


# Tears down the session and its Docker container (started with --rm, so it's
# removed on exit). Safe to call once at the end of a run (main.py does this in
# a finally block); a no-op if never connected.
def close_mcp_client() -> None:
    global _bridge
    if _bridge is not None:
        _bridge.close()
        _bridge = None
