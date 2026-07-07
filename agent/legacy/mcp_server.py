# MCP server exposing this project's GitHub fetch layer as MCP tools.
#
# This is a thin transport wrapper: every tool delegates straight to the
# existing, tested functions in fetch.py — no fetch logic (pagination, the
# max_issues/max_prs caps, PR filtering) is reimplemented here. Because
# fetch.py exposes the same three functions main.py expects, swapping MCP
# back out for direct REST is a one-line import change in main.py
# (agent.mcp_client -> agent.legacy.fetch). See ROLLBACK.md.
#
# Run as: python -m agent.legacy.mcp_server  (stdio transport). Legacy
# fallback, not used by the main pipeline — see ROLLBACK.md.

from mcp.server.fastmcp import FastMCP

from agent.legacy import fetch

mcp = FastMCP("issue_scout_github")


# The docstrings below are sent over the MCP protocol as each tool's
# description, so they are program-consumed data (hence regular strings,
# not # comments).
@mcp.tool()
def get_open_issues(owner: str, repo: str, max_issues: int = 300) -> list[dict]:
    """Open issues (excluding PRs) for owner/repo, most recently updated first, capped at max_issues."""
    return fetch.get_open_issues(owner, repo, max_issues)


@mcp.tool()
def get_open_pull_requests(owner: str, repo: str, max_prs: int = 100) -> list[dict]:
    """Open pull requests for owner/repo, most recently updated first, capped at max_prs."""
    return fetch.get_open_pull_requests(owner, repo, max_prs)


@mcp.tool()
def get_issue_comments(owner: str, repo: str, issue_number: int) -> list[dict]:
    """Full comment thread for a single issue number in owner/repo."""
    return fetch.get_issue_comments(owner, repo, issue_number)


if __name__ == "__main__":
    mcp.run(transport="stdio")
