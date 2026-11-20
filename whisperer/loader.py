"""Get a repository onto disk and turn it into chunks (code, docs, commits, issues)."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Iterator

import requests

from .chunker import chunk_file, detect_language
from .models import Chunk

IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", "target", "vendor",
               ".idea", ".vscode", "coverage", ".pytest_cache", ".mypy_cache", ".gradle", "Pods", ".dart_tool", "site-packages"}
IGNORE_FILES = {"package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml", "Cargo.lock", "Pipfile.lock",
                "composer.lock", "LICENSE", "LICENSE.txt", "COPYING"}
MAX_FILE_BYTES = 300_000


def _git(root: Path, *args: str, timeout: int = 120) -> str:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"git {' '.join(args)} failed")
    return res.stdout


def is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def git_head(root: Path) -> str | None:
    try:
        return _git(root, "rev-parse", "HEAD").strip()
    except Exception:
        return None


def parse_github(source: str) -> tuple[str, str] | None:
    m = re.match(r"^(?:https?://github\.com/|git@github\.com:)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", source.strip())
    return (m.group(1), m.group(2)) if m else None


def resolve_checkout(source: str, name: str, data_dir: Path) -> Path:
    """Local directory -> used in place. GitHub URL / owner/repo -> shallow clone into data_dir."""
    p = Path(source).expanduser()
    if p.is_dir():
        return p.resolve()
    gh = parse_github(source)
    if not gh:
        raise ValueError(f"Not a directory or GitHub repo: {source}")
    dest = data_dir / "repos" / name / "checkout"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{gh[0]}/{gh[1]}.git"
    subprocess.run(["git", "clone", "--depth", "300", url, str(dest)], check=True, capture_output=True, text=True, timeout=600)
    return dest


def pull(root: Path) -> None:
    """Fetch upstream changes for a cloned repo (no-op for repos without a remote)."""
    try:
        if _git(root, "remote").strip():
            _git(root, "pull", "--ff-only", timeout=300)
    except Exception:
        pass


def iter_files(root: Path) -> Iterator[tuple[str, str]]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
        for fn in sorted(filenames):
            if fn in IGNORE_FILES or fn.endswith((".min.js", ".map", ".lock")):
                continue
            full = Path(dirpath) / fn
            rel = full.relative_to(root).as_posix()
            if detect_language(rel) is None:
                continue
            try:
                if full.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = full.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:2048]:
                continue
            yield rel, data.decode("utf-8", "replace")


def manifest_of(root: Path) -> dict[str, str]:
    """{relative path: sha1 of content} for every indexable file."""
    return {rel: hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest() for rel, text in iter_files(root)}


def chunks_for_paths(repo: str, root: Path, paths: set[str] | None, max_lines: int) -> list[Chunk]:
    out: list[Chunk] = []
    for rel, text in iter_files(root):
        if paths is None or rel in paths:
            out.extend(chunk_file(repo, rel, text, max_lines))
    return out


# ------------------------------------------------------------------ history
def read_commits(root: Path, since_sha: str | None = None, limit: int = 300) -> list[dict]:
    """[{sha, author, date, subject, body, files}] newest first."""
    if not is_git_repo(root):
        return []
    rng = f"{since_sha}..HEAD" if since_sha else "HEAD"
    fmt = "%x1e%H%x1f%an%x1f%aI%x1f%s%x1f%b%x1f"
    try:
        raw = _git(root, "log", rng, f"-n{limit}", f"--pretty=format:{fmt}", "--name-only")
    except Exception:
        return []
    commits = []
    for rec in raw.split("\x1e"):
        if not rec.strip():
            continue
        head, _, files = rec.rpartition("\x1f")
        parts = head.split("\x1f")
        if len(parts) < 5:
            continue
        commits.append({"sha": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3],
                        "body": parts[4].strip(), "files": [f for f in files.splitlines() if f.strip()]})
    return commits


def commit_chunk(repo: str, c: dict) -> Chunk:
    body = f"Commit {c['sha'][:7]} by {c['author']} on {c['date'][:10]}\n{c['subject']}\n{c['body']}\nFiles: {', '.join(c['files'][:25])}"
    return Chunk(repo=repo, kind="commit", path=f"commit:{c['sha'][:7]}", start_line=0, end_line=0,
                 symbol=c["subject"][:80], language="git", text=body.strip(), meta={"sha": c["sha"], "files": c["files"]})


# ------------------------------------------------------------------ issues
def fetch_issues(owner: str, repo: str, token: str = "", limit: int = 100) -> list[dict]:
    """Issues + PRs from the GitHub REST API. Returns [] on any failure (offline, rate limit...)."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}/issues",
                         params={"state": "all", "per_page": min(limit, 100)}, headers=headers, timeout=20)
        if r.status_code != 200:
            return []
        return r.json()
    except Exception:
        return []


def issue_chunk(repo: str, it: dict) -> Chunk:
    labels = [l["name"] for l in it.get("labels", [])]
    is_pr = "pull_request" in it
    body = (it.get("body") or "")[:2500]
    text = f"{'PR' if is_pr else 'Issue'} #{it['number']} [{it.get('state')}] {it['title']}\nLabels: {', '.join(labels)}\n{body}"
    return Chunk(repo=repo, kind="issue", path=f"issue#{it['number']}", start_line=0, end_line=0, symbol=it["title"][:80],
                 language="github", text=text, meta={"labels": labels, "is_pr": is_pr, "url": it.get("html_url", ""),
                                                      "state": it.get("state")})
