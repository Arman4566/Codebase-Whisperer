"""The Whisperer: repo registry + cited Q&A + onboarding + sync + change summaries."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import loader, onboarding
from .actions import ActionQueue
from .config import Settings, get_settings
from .index import RepoIndex
from .llm import LLM, LLMError
from .text import content_terms, fuzzy_match, search_tokens, stem

ABSTAIN_COVERAGE = 0.5        # share of the question's key terms that must appear in the retrieved evidence
# Refuse when this share of the question's key terms appears NOWHERE in the repository. Absence from a small vocabulary
# is weak evidence (ordinary words are often missing from a 14-file repo), so small repos use a conservative threshold.
# Measured on two repos (see eval/): 0.2 wrongly refused 9/16 valid questions on a 431-token repo; 0.34 refused none.
ABSTAIN_UNKNOWN_SHARE_LARGE = 0.2
ABSTAIN_UNKNOWN_SHARE_SMALL = 0.34
LARGE_VOCAB_TOKENS = 2000


@dataclass
class RepoState:
    name: str
    source: str
    root: Path
    index: RepoIndex
    manifest: dict
    head: str | None
    gh: tuple[str, str] | None
    synced_at: float
    history: list = field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", text.strip().rstrip("/").split("/")[-1].replace(".git", "")).strip("-").lower() or "repo"


class Whisperer:
    def __init__(self, settings: Settings | None = None, llm: LLM | None = None):
        self.s = settings or get_settings()
        self.llm = llm or LLM(self.s)
        self.repos: dict[str, RepoState] = {}
        self.actions = ActionQueue(self.s, lambda name: self.repos[name].gh if name in self.repos else None)
        self._restore()

    # ================================================================= registry
    def _repo_dir(self, name: str) -> Path:
        return self.s.data_dir / "repos" / name

    def _restore(self) -> None:
        base = self.s.data_dir / "repos"
        if not base.exists():
            return
        for d in sorted(base.iterdir()):
            f = d / "state.json"
            if not f.exists():
                continue
            try:
                st = json.loads(f.read_text())
                idx = RepoIndex(d.name, d, self.llm, use_openai=self.llm.available)
                if idx.load():
                    self.repos[d.name] = RepoState(d.name, st["source"], Path(st["root"]), idx, st["manifest"], st.get("head"),
                                                   tuple(st["gh"]) if st.get("gh") else None, st.get("synced_at", 0), st.get("history", []))
            except Exception:
                continue

    def _persist(self, r: RepoState) -> None:
        d = self._repo_dir(r.name)
        d.mkdir(parents=True, exist_ok=True)
        r.index.save()
        (d / "state.json").write_text(json.dumps({"source": r.source, "root": str(r.root), "manifest": r.manifest, "head": r.head,
                                                  "gh": list(r.gh) if r.gh else None, "synced_at": r.synced_at, "history": r.history[-20:]}))

    def add_repo(self, source: str, name: str | None = None, with_issues: bool = True) -> dict:
        name = name or _slug(source)
        root = loader.resolve_checkout(source, name, self.s.data_dir)
        gh = loader.parse_github(source) or self._gh_from_remote(root)
        chunks = loader.chunks_for_paths(name, root, None, self.s.max_chunk_lines)
        chunks += [loader.commit_chunk(name, c) for c in loader.read_commits(root)]
        if gh and with_issues:
            chunks += [loader.issue_chunk(name, it) for it in loader.fetch_issues(gh[0], gh[1], self.s.github_token)]
        idx = RepoIndex(name, self._repo_dir(name), self.llm, use_openai=self.llm.available)
        idx.build(chunks)
        st = RepoState(name, source, root, idx, loader.manifest_of(root), loader.git_head(root), gh, time.time())
        self.repos[name] = st
        self._persist(st)
        return self.repo_info(name)

    @staticmethod
    def _gh_from_remote(root: Path) -> tuple[str, str] | None:
        try:
            url = loader._git(root, "remote", "get-url", "origin").strip()
            return loader.parse_github(url)
        except Exception:
            return None

    def get(self, name: str | None) -> RepoState:
        if name is None:
            if len(self.repos) == 1:
                return next(iter(self.repos.values()))
            raise KeyError("specify a repo; indexed: " + ", ".join(self.repos) if self.repos else "no repositories indexed yet")
        if name not in self.repos:
            raise KeyError(f"unknown repo {name!r}; indexed: {', '.join(self.repos) or 'none'}")
        return self.repos[name]

    def repo_info(self, name: str) -> dict:
        r = self.get(name)
        return {"name": r.name, "source": r.source, "head": r.head, "github": "/".join(r.gh) if r.gh else None,
                "synced_at": r.synced_at, **r.index.stats()}

    def list_repos(self) -> list[dict]:
        return [self.repo_info(n) for n in self.repos]

    # ================================================================= retrieval
    def search(self, query: str, repo: str | None = None, k: int | None = None, mode: str = "hybrid", kinds: set[str] | None = None) -> list[dict]:
        k = k or self.s.top_k
        states = [self.get(repo)] if repo else list(self.repos.values())
        merged = []
        for st in states:
            merged += st.index.search(query, k=k, mode=mode, kinds=kinds)
        merged.sort(key=lambda r: -r["score"])
        return merged[:k]

    def _coverage(self, question: str, results: list[dict], repo: str | None = None) -> tuple[float, list[str], list[str], int]:
        """(coverage, terms missing from the top evidence, terms missing from the WHOLE repo, repo vocabulary size).

        A key term that appears nowhere in the repository (kubernetes, kafka, graphql...) is strong evidence
        that the concept is not there, even when generic words still match some chunks.
        """
        terms = list(dict.fromkeys(stem(t) for t in content_terms(question)))
        if not terms:
            return 1.0, [], [], 0
        local: set[str] = set()
        for r in results:
            c = r["chunk"]
            local.update(search_tokens(c.text))
            local.update(search_tokens(c.path))
            local.update(search_tokens(c.symbol))
        states = [self.get(repo)] if repo else list(self.repos.values())
        world: set[str] = set()
        for st in states:
            world |= st.index.vocab()
        missing = [t for t in terms if not fuzzy_match(t, local)]
        missing_global = [t for t in terms if not fuzzy_match(t, world)]
        return 1 - len(missing) / len(terms), missing, missing_global, len(world)

    def _citation_ok(self, chunk) -> bool:
        st = self.repos.get(chunk.repo)
        if not st:
            return False
        if chunk.kind in ("commit", "issue"):
            return True
        f = st.root / chunk.path
        try:
            return f.is_file() and chunk.end_line <= len(f.read_text(errors="replace").splitlines())
        except OSError:
            return False

    def _label(self, chunk, multi: bool) -> str:
        return f"{chunk.repo}:{chunk.ref}" if multi else chunk.ref

    # ================================================================= Q&A
    def ask(self, question: str, repo: str | None = None, language: str = "English", k: int | None = None, history: list[dict] | None = None) -> dict:
        t0 = time.time()
        from .insight import resolve_followup
        retrieval_q = resolve_followup(question, history)
        multi = repo is None and len(self.repos) > 1
        results = self.search(retrieval_q, repo, k=k or self.s.top_k)
        heads = {n: (r.head or "")[:7] for n, r in self.repos.items() if repo in (None, n)}
        base = {"question": question, "retrieval_query": retrieval_q if retrieval_q != question else None, "repo": repo or ("all" if multi else next(iter(self.repos), None)), "indexed_commit": heads,
                "sources": [dict(r["chunk"].brief(), repo=r["chunk"].repo, score=round(r["score"], 4)) for r in results]}
        coverage, missing, missing_global, vocab_size = self._coverage(retrieval_q, results, repo)
        base["coverage"] = round(coverage, 2)
        n_terms = len(content_terms(retrieval_q)) or 1
        share = ABSTAIN_UNKNOWN_SHARE_LARGE if vocab_size >= LARGE_VOCAB_TOKENS else ABSTAIN_UNKNOWN_SHARE_SMALL
        unknown_to_repo = len(missing_global) / n_terms >= share
        if unknown_to_repo:
            missing = list(dict.fromkeys(missing_global + missing))
        if not results or coverage < ABSTAIN_COVERAGE or unknown_to_repo:
            closest = [self._label(r["chunk"], multi) for r in results[:3]]
            originals = {stem(t): t for t in content_terms(retrieval_q)}   # show the user's words, not stems
            shown = [originals.get(m, m) for m in missing]
            msg = (f"I couldn't find this in the indexed repository. Terms with no evidence: {', '.join(shown) or 'n/a'}. "
                   + (f"The closest (probably unrelated) matches are {', '.join(closest)}." if closest else ""))
            return {**base, "abstained": True, "mode": "abstain", "answer": msg, "missing_terms": shown, "closest": closest,
                    "claims": [], "confidence": 0.0, "elapsed_s": round(time.time() - t0, 2)}
        if self.llm.available:
            try:
                out = self._answer_llm(question, results, language, multi)
                return {**base, **out, "elapsed_s": round(time.time() - t0, 2)}
            except LLMError as e:
                base["llm_error"] = str(e)
        return {**base, **self._answer_extractive(results, multi), "elapsed_s": round(time.time() - t0, 2)}

    # ---- LLM path
    def _context(self, results: list[dict], multi: bool) -> str:
        blocks = []
        for n, r in enumerate(results, 1):
            c = r["chunk"]
            if c.kind in ("commit", "issue"):
                body = c.text[:1500]
            else:
                body = "\n".join(f"{c.start_line + i}: {l}" for i, l in enumerate(c.text.splitlines()[:140]))[:2600]
            blocks.append(f"[{n}] {self._label(c, multi)}  ({c.kind}: {c.symbol})\n{body}")
        return "\n\n".join(blocks)

    def _answer_llm(self, question: str, results: list[dict], language: str, multi: bool) -> dict:
        system = (
            "You are Codebase Whisperer, answering questions about a code repository using ONLY the numbered context snippets. "
            "Code lines are prefixed with their real line numbers. Reply as JSON: "
            '{"found": bool, "summary": str, "claims": [{"text": str, "status": "verified"|"assumption", '
            '"sources": [{"n": int, "lines": "start-end"}]}]}. '
            "RULES: every claim must be one precise statement. status=verified ONLY if a cited snippet directly shows it; "
            "otherwise status=assumption (an inference, convention, or anything not shown) and say so in the text. "
            "Cite the narrowest line range that supports the claim. If the context does not answer the question, return "
            '{"found": false, "summary": "...what is missing...", "claims": []}. Never cite a number that is not in the context. '
            f"Write the text in {language}; keep identifiers, paths and code in their original form.")
        data = self.llm.chat_json(system, f"QUESTION: {question}\n\nCONTEXT:\n{self._context(results, multi)}", max_tokens=1600)
        if not data.get("found", True):
            return {"abstained": True, "mode": "llm", "answer": data.get("summary") or "The repository does not contain enough information.",
                    "claims": [], "confidence": 0.0}
        claims, valid_n, verified_n = [], 0, 0
        for cl in data.get("claims", []):
            cites = []
            for s in cl.get("sources", []):
                n = s.get("n") if isinstance(s, dict) else s
                if not isinstance(n, int) or not 1 <= n <= len(results):
                    continue
                c = results[n - 1]["chunk"]
                if not self._citation_ok(c):
                    continue
                ref = self._label(c, multi)
                m = re.match(r"^L?(\d+)\s*-\s*L?(\d+)$", str(s.get("lines", ""))) if isinstance(s, dict) else None
                if m and c.kind not in ("commit", "issue") and c.start_line <= int(m.group(1)) <= int(m.group(2)) <= c.end_line:
                    ref = f"{c.repo + ':' if multi else ''}{c.path}:L{m.group(1)}-L{m.group(2)}"
                if ref not in cites:
                    cites.append(ref)
            status = cl.get("status", "assumption")
            if status == "verified" and not cites:  # a "verified" claim without a valid citation is downgraded
                status = "assumption"
            valid_n += bool(cites)
            verified_n += status == "verified"
            claims.append({"text": cl.get("text", ""), "status": status, "citations": cites})
        if not claims:
            return {"abstained": True, "mode": "llm", "answer": data.get("summary", "No supported claims."), "claims": [], "confidence": 0.0}
        md = [data.get("summary", "").strip(), ""]
        for c in claims:
            icon = "✅ Verified" if c["status"] == "verified" else "⚠️ Assumption"
            md.append(f"- **{icon}:** {c['text']} " + (" ".join(f"`{x}`" for x in c["citations"])))
        return {"abstained": False, "mode": "llm", "answer": "\n".join(md).strip(), "claims": claims,
                "summary": (data.get("summary") or "").strip(), "confidence": round(verified_n / len(claims), 2)}

    # ---- offline path
    def _answer_extractive(self, results: list[dict], multi: bool) -> dict:
        claims = []
        ordered = sorted(results, key=lambda r: r["chunk"].kind in ("commit", "issue"))  # code/docs first (stable)
        for r in ordered[:4]:
            c = r["chunk"]
            first = next((l.strip() for l in c.text.splitlines() if l.strip()), "")
            if c.kind == "doc":
                first = first.lstrip("#").strip()
            claims.append({"text": f"{c.kind} `{c.symbol}`: {first[:140]}", "status": "verified", "citations": [self._label(c, multi)]})
        md = ["_No OPENAI_API_KEY set - showing the most relevant evidence found in the repository (extractive mode)._", ""]
        md += [f"- ✅ **Evidence:** {c['text']} `{c['citations'][0]}`" for c in claims]
        return {"abstained": False, "mode": "extractive", "answer": "\n".join(md), "claims": claims, "confidence": 0.5}

    # ================================================================= graph (powers the 3D map in the UI)
    def graph(self, repo: str | None = None, max_nodes: int = 700) -> dict:
        """Files as nodes (sized by length / how many files import them) and import edges between them."""
        from collections import Counter
        from .chunker import detect_language, kind_for

        st = self.get(repo)
        key = (st.name, st.synced_at, max_nodes)
        cache = self.__dict__.setdefault("_graph_cache", {})
        if key in cache:
            return cache[key]
        files = dict(loader.iter_files(st.root))
        ig = onboarding.import_graph(files)
        fan = Counter(t for targets in ig.values() for t in targets)
        lines = {p: max(1, t.count("\n") + 1) for p, t in files.items()}
        ranked = sorted(files, key=lambda p: (-(fan[p] * 6 + lines[p] ** 0.5), p))[:max_nodes]
        idx = {p: i for i, p in enumerate(ranked)}
        nodes = []
        for p in ranked:
            lang = detect_language(p) or "text"
            nodes.append({"path": p, "dir": p.rsplit("/", 1)[0] if "/" in p else "", "lang": lang, "kind": kind_for(lang),
                          "lines": lines[p], "fan_in": fan[p]})
        edges = [[idx[a], idx[b]] for a, targets in ig.items() if a in idx for b in sorted(targets) if b in idx]
        out = {"repo": st.name, "head": (st.head or "")[:7], "total_files": len(files), "nodes": nodes, "edges": edges}
        cache.clear()
        cache[key] = out
        return out

    # ================================================================= navigation
    def explain_file(self, path: str, repo: str | None = None) -> dict:
        from . import insight
        return insight.explain_file(self.get(repo), path)

    def find_usages(self, symbol: str, repo: str | None = None, limit: int = 60) -> dict:
        from . import insight
        return insight.find_usages(self.get(repo), symbol, limit)

    # ================================================================= onboarding
    def onboarding_guide(self, repo: str | None = None, level: str = "beginner", goal: str = "", language: str = "English") -> dict:
        st = self.get(repo)
        issues = [c.to_dict() for c in st.index.chunks if c.kind == "issue"]
        profile = onboarding.build_profile(st.name, st.root, issues, st.head)
        md = onboarding.render_markdown(profile, level, goal)
        mode = "deterministic"
        if self.llm.available and (language.lower() != "english" or goal):
            try:
                md = onboarding.personalise_with_llm(self.llm, md, profile, level, goal, language)
                mode = "llm"
            except LLMError:
                pass
        elif self.llm.available:
            mode = "deterministic"
        return {"repo": st.name, "level": level, "goal": goal, "language": language, "mode": mode, "markdown": md,
                "unverified_paths": onboarding.unverified_paths(md, profile["all_paths"]),
                "profile": {k: v for k, v in profile.items() if k != "all_paths"}}

    # ================================================================= sync + change summaries
    def sync(self, repo: str | None = None, pull: bool = True) -> dict:
        st = self.get(repo)
        old_head = st.head
        if pull:
            loader.pull(st.root)
        new_manifest = loader.manifest_of(st.root)
        added = sorted(set(new_manifest) - set(st.manifest))
        deleted = sorted(set(st.manifest) - set(new_manifest))
        modified = sorted(p for p in new_manifest if p in st.manifest and new_manifest[p] != st.manifest[p])
        new_head = loader.git_head(st.root)
        commits = loader.read_commits(st.root, since_sha=old_head) if old_head and new_head != old_head else []
        changed = set(added) | set(modified)
        new_chunks = loader.chunks_for_paths(st.name, st.root, changed, self.s.max_chunk_lines) if changed else []
        new_chunks += [loader.commit_chunk(st.name, c) for c in commits]
        refreshed_issues = 0
        if st.gh:
            fresh = loader.fetch_issues(st.gh[0], st.gh[1], self.s.github_token)
            if fresh:
                new_chunks += [loader.issue_chunk(st.name, it) for it in fresh]
                refreshed_issues = len(fresh)
        remove = set(modified) | set(deleted) | ({c.path for c in st.index.chunks if c.kind == "issue"} if refreshed_issues else set())
        if remove or new_chunks:
            st.index.replace_paths(remove, new_chunks)
        st.manifest, st.head, st.synced_at = new_manifest, new_head, time.time()
        result = {"repo": st.name, "changed": bool(added or modified or deleted or commits), "added": added, "modified": modified,
                  "deleted": deleted, "new_commits": [{"sha": c["sha"][:7], "subject": c["subject"], "author": c["author"], "files": c["files"]} for c in commits],
                  "reindexed_chunks": len(new_chunks), "from": (old_head or "")[:7], "to": (new_head or "")[:7], "synced_at": st.synced_at}
        result["summary"] = self.summarize_changes(result)
        st.history.append({k: result[k] for k in ("from", "to", "synced_at", "summary")})
        self._persist(st)
        return result

    def summarize_changes(self, sync_result: dict, language: str = "English") -> str:
        if not sync_result["changed"]:
            return "No changes since the last sync."
        lines = [f"{len(sync_result['new_commits'])} new commit(s): "
                 + "; ".join(f"{c['sha']} {c['subject']}" for c in sync_result["new_commits"][:8]),
                 f"Files added: {', '.join(sync_result['added']) or 'none'}. Modified: {', '.join(sync_result['modified']) or 'none'}. "
                 f"Deleted: {', '.join(sync_result['deleted']) or 'none'}."]
        plain = "\n".join(lines)
        if self.llm.available:
            try:
                return self.llm.chat("Summarise repository changes for a developer in 3-5 short bullets: what changed, why it matters, and what to re-read. "
                                     f"Use only the facts given. Write in {language}.", plain, max_tokens=400)
            except LLMError:
                pass
        return plain
