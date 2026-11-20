"""Deterministic code-navigation helpers: explain a file, find usages, resolve follow-up questions.
Everything here is read straight from the checkout, so every line reference is real (no model involved)."""
from __future__ import annotations

import re
from pathlib import Path

from . import loader, onboarding
from .text import content_terms

_PRONOUNS = re.compile(r"^(and |what about |how about |so |then |why )?(it|that|this|they|those|these|its|there|the same|where is it)\b", re.I)


def resolve_followup(question: str, history: list[dict] | None) -> str:
    """Make a short follow-up ("and where is it tested?") retrievable by borrowing the previous question's key terms.
    The user's own wording is still what gets shown and answered."""
    q = question.strip()
    prev = next((h.get("q", "") for h in reversed(history or []) if h.get("q")), "")
    if not prev:
        return q
    short = len(content_terms(q)) <= 2
    if _PRONOUNS.match(q) or short:
        carried = [t for t in content_terms(prev) if t not in content_terms(q)][:6]
        if carried:
            return f"{q} {' '.join(carried)}"
    return q


def _safe_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if root.resolve() not in p.parents and p != root.resolve():
        raise ValueError("path is outside the repository")
    return p


def explain_file(st, path: str, graph_files: dict[str, str] | None = None) -> dict:
    files = graph_files if graph_files is not None else dict(loader.iter_files(st.root))
    if path not in files:
        raise KeyError(f"{path} is not an indexed file in {st.name}")
    text = files[path]
    n_lines = text.count("\n") + 1
    ig = onboarding.import_graph(files)
    imports = sorted(ig.get(path, ()))
    imported_by = sorted(p for p, t in ig.items() if path in t)
    stem = Path(path).stem
    tests = sorted({p for p in files if onboarding._is_test(p) and (p in imported_by or stem in Path(p).stem)})
    symbols = []
    for c in sorted((c for c in st.index.chunks if c.path == path and c.kind in ("code", "config")), key=lambda c: c.start_line):
        if c.symbol and c.symbol != "(module-level)":
            first = next((l.strip() for l in c.text.splitlines()[1:6] if l.strip().startswith(('"""', "'''", "//", "#", "/*", "*"))), "")
            symbols.append({"name": c.symbol, "start": c.start_line, "end": c.end_line, "ref": c.ref, "note": first.strip('"\'/#* ')[:120]})
    todos = [{"line": i, "text": l.strip()[:140]} for i, l in enumerate(text.splitlines(), 1)
             if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", l)][:10]
    commits = []
    try:
        raw = loader._git(st.root, "log", "-n5", "--pretty=format:%h\x1f%an\x1f%as\x1f%s", "--", path)
        for line in raw.splitlines():
            h, a, d, s = (line.split("\x1f") + ["", "", "", ""])[:4]
            commits.append({"sha": h, "author": a, "date": d, "subject": s})
    except Exception:
        pass
    return {"repo": st.name, "path": path, "lines": n_lines, "summary": onboarding.describe_file(path, text),
            "symbols": symbols, "imports": imports, "imported_by": imported_by, "tests": tests, "todos": todos,
            "recent_commits": commits, "verified": True}


def find_usages(st, symbol: str, limit: int = 60, files: dict[str, str] | None = None) -> dict:
    sym = symbol.strip()
    if not re.fullmatch(r"[\w.$]{2,80}", sym):
        raise ValueError("symbol must be an identifier like parse_args or Cart.add")
    name = sym.split(".")[-1]
    pat = re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")
    defs = [c for c in st.index.chunks if c.kind == "code" and c.symbol.split(".")[-1] == name]
    def_spans = {(c.path, c.start_line) for c in defs}
    files = files if files is not None else dict(loader.iter_files(st.root))
    hits, total = [], 0
    for path in sorted(files):
        for i, line in enumerate(files[path].splitlines(), 1):
            if pat.search(line):
                total += 1
                if len(hits) < limit:
                    is_def = (path, i) in def_spans or bool(re.match(rf"\s*(async\s+)?(def|class|function|const|let|var|fn|func|type)\s+{re.escape(name)}\b", line))
                    hits.append({"path": path, "line": i, "text": line.strip()[:160], "kind": "definition" if is_def else ("test" if onboarding._is_test(path) else "usage"),
                                 "ref": f"{path}:L{i}-L{i}"})
    hits.sort(key=lambda h: ({"definition": 0, "usage": 1, "test": 2}[h["kind"]], h["path"], h["line"]))
    return {"repo": st.name, "symbol": sym, "total": total, "shown": len(hits), "definitions": [c.ref for c in defs[:5]],
            "hits": hits, "found": total > 0, "verified": True}
