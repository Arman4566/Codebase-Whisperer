"""Personalised onboarding guides.

Facts (structure, entry points, key modules, beginner tasks) are computed deterministically from the
repository itself, so the guide never invents files. An LLM, when available, only rewrites/personalises
the facts; every path it mentions is afterwards checked against the real file list.
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from .loader import iter_files, read_commits
from .chunker import detect_language

ENTRY_NAMES = {"main.py", "app.py", "__main__.py", "manage.py", "server.py", "cli.py", "wsgi.py", "asgi.py", "index.js",
               "index.ts", "main.js", "main.ts", "server.js", "app.js", "main.go", "Main.java", "main.dart", "main.rs"}
BEGINNER_LABELS = {"good first issue", "good-first-issue", "help wanted", "beginner", "easy", "documentation", "docs", "starter"}
_TODO = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b[:\s-]*(.*)")
_PY_IMPORT = re.compile(r"^\s*(?:from\s+([.\w]+)\s+import\s+([\w, *]+)|import\s+([\w., ]+))", re.M)
_JS_IMPORT = re.compile(r"""(?:require\(\s*|from\s+|import\s+)['"](\.{1,2}/[^'"]+)['"]""")


def _is_test(path: str) -> bool:
    p = path.lower()
    return "/test" in p or p.startswith("test") or "_test." in p or ".test." in p or ".spec." in p or "/tests/" in p


# ------------------------------------------------------------------ import graph
def _py_modules(paths: list[str]) -> dict[str, str]:
    """dotted module name -> file. Also registers unambiguous suffixes, so `import click` resolves for src/click/__init__.py."""
    cands: dict[str, set[str]] = {}
    for p in paths:
        if p.endswith(".py"):
            dotted = p[:-3].replace("/", ".")
            if dotted.endswith(".__init__"):
                dotted = dotted[: -len(".__init__")]
            parts = dotted.split(".")
            for i in range(len(parts)):
                cands.setdefault(".".join(parts[i:]), set()).add(p)
    return {name: next(iter(files)) for name, files in cands.items() if len(files) == 1}


def import_graph(files: dict[str, str]) -> dict[str, set[str]]:
    """{file: {files it imports}} for Python and JS/TS."""
    paths = list(files)
    pymods = _py_modules(paths)
    pathset = set(paths)
    graph: dict[str, set[str]] = defaultdict(set)
    for path, text in files.items():
        if path.endswith(".py"):
            pkg = path.rsplit("/", 1)[0].replace("/", ".") if "/" in path else ""
            for m in _PY_IMPORT.finditer(text):
                frm, names, plain = m.groups()
                targets: list[str] = []
                if frm is not None:
                    base = frm
                    if frm.startswith("."):
                        up = len(frm) - len(frm.lstrip("."))
                        parts = pkg.split(".") if pkg else []
                        parts = parts[: len(parts) - (up - 1)] if up > 1 else parts
                        base = ".".join(parts + ([frm.lstrip(".")] if frm.lstrip(".") else []))
                    targets.append(base)
                    for n in re.split(r"[,\s]+", names or ""):
                        if n and n != "*":
                            targets.append(f"{base}.{n}" if base else n)
                else:
                    targets += [t.strip().split(" as ")[0] for t in (plain or "").split(",")]
                for t in targets:
                    if t in pymods and pymods[t] != path:
                        graph[path].add(pymods[t])
        elif detect_language(path) in ("javascript", "typescript"):
            here = PurePosixPath(path).parent
            for m in _JS_IMPORT.finditer(text):
                rel = (here / m.group(1)).as_posix()
                rel = re.sub(r"(^|/)\./", r"\1", rel)
                parts: list[str] = []
                for seg in rel.split("/"):
                    if seg == "..":
                        if parts:
                            parts.pop()
                    elif seg:
                        parts.append(seg)
                base = "/".join(parts)
                for cand in (base, *(base + e for e in (".js", ".ts", ".jsx", ".tsx", ".mjs")),
                             *(f"{base}/index{e}" for e in (".js", ".ts"))):
                    if cand in pathset and cand != path:
                        graph[path].add(cand)
                        break
    return graph


# ------------------------------------------------------------------ small describers
def describe_file(path: str, text: str) -> str:
    if path.endswith(".py"):
        try:
            doc = ast.get_docstring(ast.parse(text))
            if doc:
                return doc.strip().splitlines()[0]
        except SyntaxError:
            pass
    for line in text.splitlines()[:8]:
        s = line.strip()
        if s.startswith(("//", "#", "/*", "*")) and len(s.strip("/#* ")) > 8:
            return s.strip("/#* ")
    return ""


def _py_undocumented(path: str, text: str) -> list[tuple[int, str]]:
    out = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            if not ast.get_docstring(node):
                out.append((node.lineno, node.name))
    return out


# ------------------------------------------------------------------ the fact sheet
def build_profile(repo: str, root: Path, issues: list[dict] | None = None, head: str | None = None) -> dict:
    files = dict(iter_files(root))
    paths = sorted(files)
    code = [p for p in paths if detect_language(p) not in ("markdown", "text", "config", None)]
    langs = Counter(detect_language(p) for p in code)

    top: dict[str, dict] = {}
    for p in paths:
        d = p.split("/")[0] if "/" in p else "(root)"
        e = top.setdefault(d, {"files": 0, "langs": Counter()})
        e["files"] += 1
        if p in code:
            e["langs"][detect_language(p)] += 1
    tree = [{"dir": d, "files": v["files"], "languages": sorted(v["langs"])} for d, v in sorted(top.items())]

    entries = []
    for p in paths:
        if PurePosixPath(p).name in ENTRY_NAMES:
            entries.append({"path": p, "why": "conventional entry-point filename"})
        elif p.endswith(".py") and re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]', files[p]):
            entries.append({"path": p, "why": "has an `if __name__ == '__main__'` block"})
    if "package.json" in files:
        try:
            pj = json.loads(files["package.json"])
            if pj.get("main"):
                entries.append({"path": pj["main"], "why": "package.json main"})
        except Exception:
            pass
    seen, uniq = set(), []
    for e in entries:
        if e["path"] not in seen:
            seen.add(e["path"])
            uniq.append(e)

    graph = import_graph(files)
    fan_in: Counter = Counter()
    for src, targets in graph.items():
        for t in targets:
            fan_in[t] += 1
    scored = []
    for p in code:
        if _is_test(p):
            continue
        n_sym = len(re.findall(r"^\s*(?:async\s+)?(?:def|class|function)\s", files[p], re.M))
        scored.append((fan_in[p] * 3 + min(n_sym, 12) * 0.5, p))
    key_modules = [{"path": p, "imported_by": fan_in[p], "imports": sorted(graph.get(p, [])), "about": describe_file(p, files[p])}
                   for _, p in sorted(scored, reverse=True)[:7]]

    # beginner-friendly opportunities ---------------------------------------
    opp: list[dict] = []
    for it in issues or []:
        labels = {l.lower() for l in it.get("meta", {}).get("labels", [])}
        if it.get("meta", {}).get("state") == "open" and labels & BEGINNER_LABELS:
            opp.append({"type": "issue", "ref": it["path"], "title": it["symbol"], "url": it.get("meta", {}).get("url", "")})
    for p in code:
        if _is_test(p):
            continue
        for i, line in enumerate(files[p].splitlines(), 1):
            m = _TODO.search(line)
            if m and len(opp) < 40:
                opp.append({"type": "todo", "ref": f"{p}:L{i}", "title": f"{m.group(1)}: {m.group(2).strip()[:90]}"})
    n_docs = 0
    for p in code:
        if p.endswith(".py") and not _is_test(p):
            for ln, name in _py_undocumented(p, files[p])[:2]:
                if n_docs < 4:
                    opp.append({"type": "docs", "ref": f"{p}:L{ln}", "title": f"Add a docstring to `{name}`"})
                    n_docs += 1
    test_text = "\n".join(files[p] for p in paths if _is_test(p))
    for p in code:
        if not _is_test(p) and p not in {e["path"] for e in uniq}:
            stem = PurePosixPath(p).stem
            if stem not in ("__init__",) and stem not in test_text:
                opp.append({"type": "tests", "ref": p, "title": f"No test mentions `{stem}` - add tests"})

    readme_name = next((p for p in paths if p.lower() in ("readme.md", "readme.rst", "readme.txt")), None)
    readme_intro, readme_ref = "", ""
    if readme_name:
        lines = files[readme_name].splitlines()
        buf, start = [], 0
        for i, l in enumerate(lines, 1):
            t = l.strip()
            # prose only: skip headings, HTML blocks, badges/images, rules, tables and code fences
            if t and not t.startswith(("#", "<", "![", "[![", "---", "===", "|", "```", "[!")):
                if not buf:
                    start = i
                buf.append(t)
            elif buf:
                break
        readme_intro, readme_ref = " ".join(buf)[:400], f"{readme_name}:L{start}-L{start + len(buf) - 1}"
    contributing = ""
    cname = next((p for p in paths if PurePosixPath(p).name.lower().startswith("contributing")), None)
    if cname:
        contributing = "\n".join(l for l in files[cname].splitlines() if l.strip())[:900]

    commits = read_commits(root, limit=8)
    return {"repo": repo, "head": head, "file_count": len(paths), "languages": dict(langs), "tree": tree,
            "entry_points": uniq, "key_modules": key_modules, "opportunities": opp[:14],
            "readme_intro": readme_intro, "readme_ref": readme_ref, "contributing": contributing,
            "contributing_file": cname, "recent_commits": [{"sha": c["sha"][:7], "subject": c["subject"], "date": c["date"][:10]} for c in commits],
            "all_paths": paths}


# ------------------------------------------------------------------ rendering
def render_markdown(p: dict, level: str = "beginner", goal: str = "") -> str:
    out = [f"# Onboarding guide: {p['repo']}",
           f"_Level: **{level}**" + (f" · Goal: **{goal}**" if goal else "") +
           f" · {p['file_count']} files · indexed commit `{(p['head'] or 'n/a')[:7]}`_", ""]
    if level == "beginner" or not p["readme_intro"]:
        out += ["## 1. What is this project?", f"{p['readme_intro'] or 'No README summary found.'} (`{p['readme_ref']}`)" if p["readme_ref"] else "No README found.", ""]
    out += ["## 2. Architecture at a glance", "| Folder | Files | Languages |", "|---|---|---|"]
    out += [f"| `{t['dir']}` | {t['files']} | {', '.join(t['languages']) or '-'} |" for t in p["tree"]]
    out += ["", "## 3. Where execution starts"]
    out += [f"- `{e['path']}` - {e['why']}" for e in p["entry_points"]] or ["- No conventional entry point detected (**assumption:** this may be a library)."]
    out += ["", "## 4. Key modules (ranked by how many files depend on them)"]
    for m in p["key_modules"]:
        dep = f", imports {', '.join('`%s`' % x for x in m['imports'])}" if m["imports"] else ""
        out.append(f"- `{m['path']}` - imported by {m['imported_by']} file(s){dep}. {m['about']}".rstrip())
    reading = [e["path"] for e in p["entry_points"][:1]] + [m["path"] for m in p["key_modules"][:4]]
    reading = list(dict.fromkeys(reading))
    if level == "beginner" and reading:
        out += ["", "**Suggested reading order:** " + " → ".join(f"`{r}`" for r in reading)]
    out += ["", "## 5. Beginner-friendly ways to contribute"]
    out += [f"- **{o['type']}** `{o['ref']}` - {o['title']}" + (f" ({o['url']})" if o.get("url") else "") for o in p["opportunities"]] \
        or ["- Nothing obvious found; start by improving docs."]
    if p["contributing"]:
        out += ["", f"## 6. How to contribute (from `{p['contributing_file']}`)", p["contributing"]]
    if p["recent_commits"]:
        out += ["", "## 7. Recent activity"] + [f"- `{c['sha']}` {c['date']} - {c['subject']}" for c in p["recent_commits"]]
    return "\n".join(out)


_PATHLIKE = re.compile(r"`([\w./-]+\.[A-Za-z]{1,5})(?::L\d+(?:-L?\d+)?)?`")


def unverified_paths(markdown: str, all_paths: list[str]) -> list[str]:
    known = set(all_paths)
    bad = []
    for m in _PATHLIKE.finditer(markdown):
        cand = m.group(1)
        if cand not in known and not any(k.endswith("/" + cand) for k in known) and cand not in bad and "." in cand:
            if detect_language(cand):
                bad.append(cand)
    return bad


def personalise_with_llm(llm, markdown: str, profile: dict, level: str, goal: str, language: str) -> str:
    system = ("You rewrite a factual onboarding guide for a developer. Keep EVERY file path and line reference exactly "
              "as given and never mention a file that is not in the facts. Do not invent features. Mark inferences as "
              "'Assumption:'. Keep it concise and well structured in Markdown.")
    user = (f"Reader level: {level}\nReader goal: {goal or 'make a first contribution'}\nWrite in: {language}\n\n"
            f"FACTS (JSON):\n{json.dumps({k: v for k, v in profile.items() if k != 'all_paths'})[:9000]}\n\n"
            f"DRAFT GUIDE:\n{markdown}")
    return llm.chat(system, user, max_tokens=2200, temperature=0.2)
