"""Hybrid retrieval: BM25 (exact identifiers) + dense (semantic) fused with reciprocal rank fusion.

Dense backend is OpenAI embeddings when a key is set, otherwise a local char-n-gram TF-IDF
(which also copes well with camelCase / snake_case identifiers), so everything runs offline.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .llm import LLM, LLMError
from .models import Chunk
from .text import STOPWORDS, query_tokens, search_tokens, stem, tokenize


HISTORY_WORDS = {"commit", "commits", "changed", "change", "changes", "history", "when", "who", "why", "introduced", "recent",
                 "recently", "latest", "issue", "issues", "pr", "prs", "bug", "bugs", "fixed", "release", "author", "added",
                 "removed", "blame", "log", "version", "merged"}


DEFINITION_WORDS = {"where", "defined", "definition", "implemented", "implementation", "declared", "located", "find", "locate"}


# ------------------------------------------------------------------ BM25
class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.doc_len = np.array([len(d) for d in docs], dtype=float)
        self.avgdl = float(self.doc_len.mean()) if self.n else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for term, tf in Counter(d).items():
                self.postings[term].append((i, tf))
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def scores(self, query_tokens: Iterable[str]) -> np.ndarray:
        s = np.zeros(self.n)
        if not self.n:
            return s
        for t in set(query_tokens):
            for i, tf in self.postings.get(t, ()):
                norm = self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1))
                s[i] += self.idf[t] * tf * (self.k1 + 1) / (tf + norm)
        return s


# ------------------------------------------------------------------ dense backends
class LocalDense:
    name = "local-char-tfidf"

    def __init__(self):
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1, max_features=300_000)
        self.matrix = None

    @staticmethod
    def _prep(text: str) -> str:
        return " ".join(tokenize(text))

    def fit(self, chunks: list[Chunk]) -> None:
        if not chunks:
            self.matrix = None
            return
        self.matrix = self.vec.fit_transform([self._prep(c.search_text) for c in chunks])

    def scores(self, query: str) -> np.ndarray:
        if self.matrix is None:
            return np.zeros(0)
        q = self.vec.transform([self._prep(query)])
        return (self.matrix @ q.T).toarray().ravel()


class OpenAIDense:
    name = "openai-embeddings"

    def __init__(self, llm: LLM, cache_dir: Path):
        self.llm = llm
        self.cache_dir = cache_dir
        self.cache: dict[str, np.ndarray] = {}
        self.matrix: np.ndarray | None = None
        self._load()

    def _load(self) -> None:
        f = self.cache_dir / "emb_cache.json"
        if f.exists():
            try:
                self.cache = {k: np.asarray(v, dtype=np.float32) for k, v in json.loads(f.read_text()).items()}
            except Exception:
                self.cache = {}

    def _save(self, keep: set[str]) -> None:
        self.cache = {k: v for k, v in self.cache.items() if k in keep}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "emb_cache.json").write_text(json.dumps({k: v.round(5).tolist() for k, v in self.cache.items()}))

    def fit(self, chunks: list[Chunk]) -> None:
        keys = [c.content_hash for c in chunks]
        missing = [(k, c) for k, c in zip(keys, chunks) if k not in self.cache]
        if missing:  # only NEW or CHANGED chunks cost API calls
            vecs = self.llm.embed([c.search_text for _, c in missing])
            for (k, _), v in zip(missing, vecs):
                a = np.asarray(v, dtype=np.float32)
                self.cache[k] = a / (np.linalg.norm(a) or 1.0)
        self._save(set(keys))
        self.matrix = np.vstack([self.cache[k] for k in keys]) if keys else None

    def scores(self, query: str) -> np.ndarray:
        if self.matrix is None:
            return np.zeros(0)
        q = np.asarray(self.llm.embed([query])[0], dtype=np.float32)
        q /= np.linalg.norm(q) or 1.0
        return self.matrix @ q


# ------------------------------------------------------------------ the index
class RepoIndex:
    def __init__(self, repo: str, store_dir: Path, llm: LLM | None = None, use_openai: bool = False):
        self.repo = repo
        self.store_dir = store_dir
        self.llm = llm
        self.use_openai = use_openai and llm is not None and llm.available
        self.chunks: list[Chunk] = []
        self.bm25: BM25 | None = None
        self.dense = None
        self.dense_error: str | None = None

    # -------------------------------------------------------------- build / update
    def build(self, chunks: list[Chunk]) -> None:
        self.chunks = list(chunks)
        self._refit()

    def replace_paths(self, remove_paths: set[str], new_chunks: list[Chunk]) -> None:
        self.chunks = [c for c in self.chunks if c.path not in remove_paths] + list(new_chunks)
        self._refit()

    def add_chunks(self, new_chunks: list[Chunk]) -> None:
        known = {c.id for c in self.chunks}
        self.chunks += [c for c in new_chunks if c.id not in known]
        self._refit()

    def _refit(self) -> None:
        self.bm25 = BM25([search_tokens(c.search_text) for c in self.chunks])
        self._sym_index: dict[str, list[int]] = {}
        for i, c in enumerate(self.chunks):
            if c.kind == "code":
                self._sym_index.setdefault(self._base_symbol(c), []).append(i)
        self.dense_error = None
        self.dense = None
        if self.use_openai:
            try:
                d = OpenAIDense(self.llm, self.store_dir)
                d.fit(self.chunks)
                self.dense = d
            except LLMError as e:  # fall back gracefully, keep the demo alive
                self.dense_error = str(e)
        if self.dense is None:
            d = LocalDense()
            d.fit(self.chunks)
            self.dense = d

    @staticmethod
    def _base_symbol(c: Chunk) -> str:
        return c.symbol.split(" (part")[0].split(".")[-1].lower()

    def vocab(self) -> set[str]:
        """Every (stemmed) token that occurs anywhere in this repository."""
        return set(self.bm25.postings) if self.bm25 else set()

    # -------------------------------------------------------------- persistence
    def save(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        (self.store_dir / "chunks.json").write_text(json.dumps([c.to_dict() for c in self.chunks]))

    def load(self) -> bool:
        f = self.store_dir / "chunks.json"
        if not f.exists():
            return False
        self.chunks = [Chunk.from_dict(d) for d in json.loads(f.read_text())]
        self._refit()
        return True

    # -------------------------------------------------------------- search
    def search(self, query: str, k: int = 8, mode: str = "hybrid", kinds: set[str] | None = None,
               max_per_file: int = 3) -> list[dict]:
        """mode: hybrid | bm25 | dense. Returns [{chunk, score, bm25, dense}] best first."""
        if not self.chunks:
            return []
        n = len(self.chunks)
        raw = [t for t in tokenize(query) if t not in STOPWORDS]
        q_tokens = query_tokens(query)
        bm = self.bm25.scores(q_tokens)
        try:
            dn = self.dense.scores(query)
        except LLMError:
            dn = np.zeros(n)
        if mode == "bm25":
            fused = bm.copy()
        elif mode == "dense":
            fused = dn.copy()
        else:
            fused = np.zeros(n)
            for arr in (bm, dn):
                order = np.argsort(-arr)[:60]
                for rank, i in enumerate(order):
                    if arr[i] > 0:
                        fused[i] += 1.0 / (60 + rank + 1)
            qset = set(q_tokens)
            all_words = set(tokenize(query))
            history_intent = bool(all_words & HISTORY_WORDS)
            test_intent = bool(all_words & {"test", "tests", "pytest", "unittest", "testing", "fixture", "fixtures"})
            # definition lookup: a code chunk whose symbol IS a queried identifier is a candidate even if BM25 missed it
            definition_intent = bool(all_words & DEFINITION_WORDS)
            sym_boost = 0.035 if definition_intent else 0.02   # "where is X defined" -> the symbol named X wins
            for tok in dict.fromkeys(raw):
                if len(tok) >= 4:
                    for i in self._sym_index.get(tok, ()):
                        fused[i] += sym_boost
            for i, c in enumerate(self.chunks):
                if fused[i] <= 0:
                    continue
                meta_tokens = {stem(t) for t in tokenize(c.path)} | {stem(t) for t in tokenize(c.symbol)}
                overlap = len(qset & meta_tokens)
                if overlap:
                    fused[i] += 0.004 * min(overlap, 3)
                # history evidence is demoted unless the question is about history
                if c.kind in ("commit", "issue") and not history_intent:
                    fused[i] *= 0.7
                name = c.path.rsplit("/", 1)[-1].lower()
                if not test_intent and ("/tests/" in "/" + c.path.lower() or name.startswith("test_") or name.endswith("_test.py")):
                    fused[i] *= 0.8
                if not history_intent and name.startswith(("changes", "changelog", "history", "news", "release")):
                    fused[i] *= 0.7
        results, per_file = [], Counter()
        for i in np.argsort(-fused):
            if fused[i] <= 0 or len(results) >= k:
                break
            c = self.chunks[i]
            if kinds and c.kind not in kinds:
                continue
            if per_file[c.path] >= max_per_file:
                continue
            per_file[c.path] += 1
            results.append({"chunk": c, "score": float(fused[i]), "bm25": float(bm[i]), "dense": float(dn[i]) if len(dn) else 0.0})
        return results

    def stats(self) -> dict:
        kinds = Counter(c.kind for c in self.chunks)
        files = {c.path for c in self.chunks if c.kind in ("code", "doc", "config")}
        return {"chunks": len(self.chunks), "files": len(files), "kinds": dict(kinds),
                "dense_backend": getattr(self.dense, "name", None), "dense_error": self.dense_error}
