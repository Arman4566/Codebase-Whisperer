"""Human-in-the-loop action queue.

The agent (and the MCP tools) can only PROPOSE actions. Nothing touches GitHub until a human
calls `approve()` through the web UI / HTTP API / CLI. `approve` is deliberately NOT exposed
as an MCP tool, so a model can never approve its own proposal.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import requests

from .config import Settings

KINDS = {"create_issue", "draft_pull_request"}


class ActionError(RuntimeError):
    pass


class ActionQueue:
    def __init__(self, settings: Settings, gh_lookup: Callable[[str], tuple[str, str] | None]):
        self.s = settings
        self.gh_lookup = gh_lookup
        self.path = settings.data_dir / "actions.json"
        self.audit_path = settings.data_dir / "audit.log"
        self._lock = threading.Lock()
        self.items: dict[str, dict] = {}
        if self.path.exists():
            try:
                self.items = json.loads(self.path.read_text())
            except Exception:
                self.items = {}

    # ------------------------------------------------------------- persistence
    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, indent=2))

    def _audit(self, event: str, item: dict, **extra) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.time(), "event": event, "id": item["id"], "kind": item["kind"], "repo": item["repo"], **extra}
        with self.audit_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    # ------------------------------------------------------------- propose (safe: never executes)
    def propose(self, kind: str, repo: str, title: str, body: str, *, labels: list[str] | None = None,
                head: str = "", base: str = "main", patch: str = "", proposed_by: str = "agent") -> dict:
        if kind not in KINDS:
            raise ActionError(f"unknown action kind {kind!r}; expected one of {sorted(KINDS)}")
        if not title.strip():
            raise ActionError("title is required")
        item = {
            "id": uuid.uuid4().hex[:10], "kind": kind, "repo": repo, "title": title.strip(), "body": body,
            "labels": labels or [], "head": head, "base": base, "patch": patch, "status": "pending",
            "proposed_by": proposed_by, "created_at": time.time(), "decided_at": None, "decided_by": None, "result": None,
        }
        with self._lock:
            self.items[item["id"]] = item
            self._save()
            self._audit("proposed", item, proposed_by=proposed_by)
        return item

    def list(self, status: str | None = None) -> list[dict]:
        items = sorted(self.items.values(), key=lambda i: i["created_at"], reverse=True)
        return [i for i in items if status is None or i["status"] == status]

    def get(self, action_id: str) -> dict:
        if action_id not in self.items:
            raise ActionError(f"no such action: {action_id}")
        return self.items[action_id]

    # ------------------------------------------------------------- human decisions
    def reject(self, action_id: str, by: str = "human", reason: str = "") -> dict:
        with self._lock:
            item = self.get(action_id)
            if item["status"] != "pending":
                raise ActionError(f"action {action_id} is already {item['status']}")
            item.update(status="rejected", decided_at=time.time(), decided_by=by, result={"reason": reason})
            self._save()
            self._audit("rejected", item, by=by, reason=reason)
            return item

    def approve(self, action_id: str, by: str = "human", edits: dict | None = None) -> dict:
        """Execute a pending action. `edits` lets the reviewer change title/body/labels before it runs."""
        with self._lock:
            item = self.get(action_id)
            if item["status"] != "pending":
                raise ActionError(f"action {action_id} is already {item['status']}")
            for k in ("title", "body", "labels", "head", "base"):
                if edits and k in edits:
                    item[k] = edits[k]
            item.update(status="approved", decided_at=time.time(), decided_by=by)
            try:
                item["result"] = self._execute(item)
            except Exception as e:  # keep the record; never lose the human's decision
                item["status"] = "failed"
                item["result"] = {"error": str(e)}
            self._save()
            self._audit(item["status"], item, by=by, result=item["result"])
            return item

    # ------------------------------------------------------------- execution
    def _execute(self, item: dict) -> dict:
        gh = self.gh_lookup(item["repo"])
        if not gh:
            return {"executed": False, "dry_run": True, "reason": "repository has no GitHub remote (local folder)"}
        if not (self.s.allow_github_writes and self.s.github_token):
            return {"executed": False, "dry_run": True,
                    "reason": "approved, but GitHub writes are disabled (set WHISPERER_ALLOW_GITHUB_WRITES=1 and GITHUB_TOKEN)",
                    "would_post_to": f"{gh[0]}/{gh[1]}"}
        owner, repo = gh
        headers = {"Authorization": f"Bearer {self.s.github_token}", "Accept": "application/vnd.github+json"}
        if item["kind"] == "create_issue":
            r = requests.post(f"https://api.github.com/repos/{owner}/{repo}/issues", headers=headers, timeout=30,
                              json={"title": item["title"], "body": item["body"], "labels": item["labels"]})
        else:
            if not item["head"]:
                return {"executed": False, "dry_run": True,
                        "reason": "a pull request needs an existing pushed branch in `head`; draft text saved only"}
            r = requests.post(f"https://api.github.com/repos/{owner}/{repo}/pulls", headers=headers, timeout=30,
                              json={"title": item["title"], "body": item["body"], "head": item["head"],
                                    "base": item["base"], "draft": True})
        if r.status_code not in (200, 201):
            raise ActionError(f"GitHub returned {r.status_code}: {r.text[:300]}")
        data = r.json()
        return {"executed": True, "url": data.get("html_url"), "number": data.get("number")}
