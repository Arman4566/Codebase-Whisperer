"""MCP server exposing Codebase Whisperer to any MCP client (Claude Desktop, Cursor, ...).

Read tools answer questions. Write tools only PROPOSE actions into the approval queue.
There is intentionally NO approve/execute tool here: a human approves in the web UI, API or CLI.
"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from .agent import Whisperer

mcp = MCPServer("codebase-whisperer", instructions=(
    "Answer questions about indexed repositories with file:line citations. Write actions (issues, pull requests) are only "
    "proposed and wait for explicit human approval - never claim an action was executed unless the human approved it."))

_w: Whisperer | None = None


def whisperer() -> Whisperer:
    global _w
    if _w is None:
        _w = Whisperer()
    return _w


@mcp.tool()
def list_repositories() -> str:
    """List indexed repositories with their indexed commit and size."""
    return json.dumps(whisperer().list_repos(), indent=2)


@mcp.tool()
def ask_codebase(question: str, repo: str | None = None, language: str = "English") -> str:
    """Ask a question about the codebase. Returns an answer whose claims are tagged verified/assumption with file:line citations,
    or says the information is not in the repository."""
    return json.dumps(whisperer().ask(question, repo, language), indent=2)


@mcp.tool()
def explain_file(path: str, repo: str | None = None) -> str:
    """Structure of one file: symbols with line ranges, what it imports, what imports it, related tests, TODOs, recent commits."""
    return json.dumps(whisperer().explain_file(path, repo), indent=2)


@mcp.tool()
def find_usages(symbol: str, repo: str | None = None) -> str:
    """Every definition and usage of an identifier, with file:line references (definitions first, tests last)."""
    return json.dumps(whisperer().find_usages(symbol, repo), indent=2)


@mcp.tool()
def search_code(query: str, repo: str | None = None, k: int = 8) -> str:
    """Hybrid (BM25 + semantic) search. Returns chunks with exact file paths and line ranges."""
    return json.dumps([dict(r["chunk"].brief(), score=round(r["score"], 4)) for r in whisperer().search(query, repo, k)], indent=2)


@mcp.tool()
def get_onboarding_guide(repo: str | None = None, level: str = "beginner", goal: str = "", language: str = "English") -> str:
    """Generate a personalised onboarding guide: architecture, entry points, key modules and beginner-friendly tasks."""
    return whisperer().onboarding_guide(repo, level, goal, language)["markdown"]


@mcp.tool()
def sync_repository(repo: str | None = None) -> str:
    """Pull the latest changes, incrementally re-index changed files, and return a change summary."""
    r = whisperer().sync(repo)
    return json.dumps({k: r[k] for k in ("repo", "changed", "from", "to", "added", "modified", "deleted", "summary")}, indent=2)


@mcp.tool()
def propose_github_issue(repo: str, title: str, body: str, labels: list[str] | None = None) -> str:
    """PROPOSE a GitHub issue. It is NOT created until a human approves it."""
    item = whisperer().actions.propose("create_issue", repo, title, body, labels=labels, proposed_by="mcp")
    return json.dumps({"status": "pending_human_approval", "action_id": item["id"],
                       "note": "Not executed. Ask the human to approve it in the Whisperer UI/CLI."})


@mcp.tool()
def draft_pull_request(repo: str, title: str, body: str, head_branch: str = "", base_branch: str = "main", patch: str = "") -> str:
    """PROPOSE a draft pull request (text + optional patch). It is NOT opened until a human approves it."""
    item = whisperer().actions.propose("draft_pull_request", repo, title, body, head=head_branch, base=base_branch, patch=patch, proposed_by="mcp")
    return json.dumps({"status": "pending_human_approval", "action_id": item["id"],
                       "note": "Not executed. Ask the human to approve it in the Whisperer UI/CLI."})


@mcp.tool()
def list_pending_actions() -> str:
    """Show actions that are waiting for human approval."""
    return json.dumps([{k: i[k] for k in ("id", "kind", "repo", "title", "status")} for i in whisperer().actions.list("pending")], indent=2)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
