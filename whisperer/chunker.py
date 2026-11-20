"""Code-aware chunking.

Chunks follow the structure of the code (functions, classes, methods, markdown
sections) rather than fixed token windows, and every chunk keeps its exact
file path + line range so answers can cite `path:L10-L42`.
"""
from __future__ import annotations

import ast
import re

from .models import Chunk

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".java": "java", ".go": "go", ".rs": "rust", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".cc": "cpp", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby", ".php": "php", ".kt": "kotlin", ".dart": "dart",
    ".swift": "swift", ".sh": "shell", ".sql": "sql", ".md": "markdown", ".rst": "markdown", ".txt": "text",
    ".json": "config", ".yaml": "config", ".yml": "config", ".toml": "config", ".ini": "config", ".cfg": "config",
    ".html": "html", ".css": "css", ".vue": "javascript",
}
SPECIAL_NAMES = {"Dockerfile": "config", "Makefile": "config", "README": "markdown"}
BRACE_LANGS = {"javascript", "typescript", "java", "go", "rust", "c", "cpp", "csharp", "php", "kotlin", "dart", "swift"}

_DECL = re.compile(
    r"""^\s*(?:export\s+)?(?:default\s+)?(?:(?:public|private|protected|static|final|abstract|async|pub|override|open|internal)\s+)*
        (?:
          (?P<kw>function|class|interface|enum|struct|trait|impl|fn|func|type|object)\s*\*?\s*(?P<name1>[A-Za-z_$][\w$]*)
         |(?:const|let|var)\s+(?P<name2>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*[\w<>\[\]|, .]+)?\s*=>
        )""",
    re.VERBOSE,
)
_METHOD = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final|abstract|async|override|synchronized)\s+)*"
    r"(?:[\w<>\[\],.?*&]+\s+)+(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws\s+[\w, .]+)?\s*\{\s*$"
)
_NOT_METHODS = {"if", "for", "while", "switch", "catch", "return", "else", "synchronized", "try", "new", "do"}
_CONTAINER_KW = {"class", "interface", "struct", "trait", "impl", "enum", "object"}


def detect_language(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if name in SPECIAL_NAMES:
        return SPECIAL_NAMES[name]
    dot = name.rfind(".")
    if dot == -1:
        return None
    return LANG_BY_EXT.get(name[dot:].lower())


def kind_for(language: str) -> str:
    if language == "markdown" or language == "text":
        return "doc"
    if language == "config":
        return "config"
    return "code"


# ---------------------------------------------------------------- helpers
def _mk(repo, path, language, lines, start, end, symbol) -> Chunk:
    body = "\n".join(lines[start - 1 : end])
    return Chunk(repo=repo, kind=kind_for(language), path=path, start_line=start, end_line=end,
                 symbol=symbol, language=language, text=body)


def _window(repo, path, language, lines, start, end, symbol, max_lines, overlap=10) -> list[Chunk]:
    """Split [start, end] into overlapping windows of <= max_lines lines."""
    if end - start + 1 <= max_lines:
        return [_mk(repo, path, language, lines, start, end, symbol)]
    out, cur, part = [], start, 1
    while cur <= end:
        stop = min(end, cur + max_lines - 1)
        out.append(_mk(repo, path, language, lines, cur, stop, f"{symbol} (part {part})"))
        if stop == end:
            break
        cur = stop - overlap + 1
        part += 1
    return out


def _fill_gaps(repo, path, language, lines, spans, max_lines, label="(module-level)") -> list[Chunk]:
    """Emit chunks for lines not covered by any span (imports, constants, scripts)."""
    covered = [False] * (len(lines) + 2)
    for s, e, *_ in spans:
        for i in range(s, e + 1):
            covered[i] = True
    out, i, n = [], 1, len(lines)
    while i <= n:
        if covered[i]:
            i += 1
            continue
        j = i
        while j <= n and not covered[j]:
            j += 1
        seg_s, seg_e = i, j - 1
        while seg_s <= seg_e and not lines[seg_s - 1].strip():
            seg_s += 1
        while seg_e >= seg_s and not lines[seg_e - 1].strip():
            seg_e -= 1
        if seg_e >= seg_s and any(lines[k - 1].strip() for k in range(seg_s, seg_e + 1)):
            out.extend(_window(repo, path, language, lines, seg_s, seg_e, label, max_lines))
        i = j
    return out


# ---------------------------------------------------------------- python
def _chunk_python(repo, path, text, lines, max_lines) -> list[Chunk] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    spans: list[tuple[int, int, str]] = []

    def start_of(node) -> int:
        decos = [d.lineno for d in getattr(node, "decorator_list", [])]
        return min([node.lineno] + decos)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((start_of(node), node.end_lineno, node.name))
        elif isinstance(node, ast.ClassDef):
            s, e = start_of(node), node.end_lineno
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if e - s + 1 > max_lines and methods:
                first = start_of(methods[0])
                if first > s:
                    spans.append((s, first - 1, node.name))
                for m in methods:
                    spans.append((start_of(m), m.end_lineno, f"{node.name}.{m.name}"))
                # class-level attrs between methods are picked up by gap filler
            else:
                spans.append((s, e, node.name))
    spans.sort()
    chunks: list[Chunk] = []
    for s, e, sym in spans:
        chunks.extend(_window(repo, path, "python", lines, s, e, sym, max_lines))
    chunks.extend(_fill_gaps(repo, path, "python", lines, spans, max_lines))
    return chunks


# ---------------------------------------------------------------- brace languages
def _find_decls(lines: list[str]) -> list[tuple[int, str, bool]]:
    """[(line_no, name, is_container)]"""
    decls = []
    for idx, line in enumerate(lines, 1):
        m = _DECL.match(line)
        if m:
            name = m.group("name1") or m.group("name2")
            decls.append((idx, name, (m.group("kw") or "") in _CONTAINER_KW))
            continue
        m = _METHOD.match(line)
        if m and m.group("name") not in _NOT_METHODS:
            decls.append((idx, m.group("name"), False))
    return decls


def _brace_end(lines: list[str], start: int, limit: int) -> int | None:
    depth, seen = 0, False
    for i in range(start, min(len(lines), start + limit) + 1):
        code = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', lines[i - 1])
        code = code.split("//")[0]
        for ch in code:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
        if seen and depth <= 0:
            return i
        if not seen and i - start >= 3:
            return None
    return None


def _chunk_braces(repo, path, language, lines, max_lines) -> list[Chunk]:
    decls = _find_decls(lines)
    spans: list[tuple[int, int, str]] = []
    covered_until = 0
    container: tuple[str, int] | None = None  # (name, end)
    limit = max_lines * 6
    for pos, (start, name, is_container) in enumerate(decls):
        if start <= covered_until:
            continue
        end = _brace_end(lines, start, limit)
        if end is None:
            nxt = decls[pos + 1][0] - 1 if pos + 1 < len(decls) else len(lines)
            end = min(nxt, start + max_lines - 1)
        sym = name
        if container and start <= container[1]:
            sym = f"{container[0]}.{name}"
        if is_container and end - start + 1 > max_lines:
            nxt_start = next((d[0] for d in decls[pos + 1 :] if d[0] <= end), None)
            header_end = (nxt_start - 1) if nxt_start else min(end, start + max_lines - 1)
            if header_end >= start:
                spans.append((start, header_end, name))
            container = (name, end)
            continue
        spans.append((start, end, sym))
        covered_until = end
    chunks: list[Chunk] = []
    for s, e, sym in spans:
        chunks.extend(_window(repo, path, language, lines, s, e, sym, max_lines))
    chunks.extend(_fill_gaps(repo, path, language, lines, spans, max_lines))
    return chunks


# ---------------------------------------------------------------- markdown / text / config
def _chunk_markdown(repo, path, lines, max_lines) -> list[Chunk]:
    heads = [(i, re.sub(r"^#+\s*", "", l).strip()) for i, l in enumerate(lines, 1) if re.match(r"^#{1,6}\s+\S", l)]
    if not heads:
        return _chunk_windows(repo, path, "markdown", lines, max_lines)
    spans: list[tuple[int, int, str]] = []
    if heads[0][0] > 1:
        spans.append((1, heads[0][0] - 1, "(intro)"))
    for k, (ln, title) in enumerate(heads):
        end = (heads[k + 1][0] - 1) if k + 1 < len(heads) else len(lines)
        spans.append((ln, end, title))
    out: list[Chunk] = []
    for s, e, sym in spans:
        while e > s and not lines[e - 1].strip():
            e -= 1
        if any(lines[i - 1].strip() for i in range(s, e + 1)):
            out.extend(_window(repo, path, "markdown", lines, s, e, sym, max_lines))
    return out


def _chunk_windows(repo, path, language, lines, max_lines, size=60, overlap=10) -> list[Chunk]:
    size = min(size, max_lines)
    out, cur = [], 1
    while cur <= len(lines):
        stop = min(len(lines), cur + size - 1)
        if any(l.strip() for l in lines[cur - 1 : stop]):
            out.append(_mk(repo, path, language, lines, cur, stop, f"lines {cur}-{stop}"))
        if stop == len(lines):
            break
        cur = stop - overlap + 1
    return out


# ---------------------------------------------------------------- public API
def chunk_file(repo: str, path: str, text: str, max_lines: int = 120) -> list[Chunk]:
    language = detect_language(path)
    if language is None or not text.strip():
        return []
    lines = text.splitlines()
    chunks: list[Chunk] | None = None
    if language == "python":
        chunks = _chunk_python(repo, path, text, lines, max_lines)
        if chunks is None:
            chunks = _chunk_windows(repo, path, language, lines, max_lines)
    elif language in BRACE_LANGS:
        chunks = _chunk_braces(repo, path, language, lines, max_lines)
    elif language == "markdown":
        chunks = _chunk_markdown(repo, path, lines, max_lines)
    else:
        chunks = _chunk_windows(repo, path, language, lines, max_lines)
    chunks.sort(key=lambda c: (c.start_line, c.end_line))
    return chunks
