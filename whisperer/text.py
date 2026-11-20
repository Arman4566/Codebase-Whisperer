"""Tokenisation helpers shared by retrieval and the abstain/coverage check."""
from __future__ import annotations

import re

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "of", "in", "on", "for", "and", "or", "not",
    "this", "that", "these", "those", "it", "its", "as", "at", "by", "with", "from", "into", "how", "what", "where",
    "when", "why", "which", "who", "does", "do", "did", "can", "could", "should", "would", "i", "me", "my", "we",
    "you", "your", "there", "any", "all", "about", "explain", "describe", "tell", "show", "give", "work", "works",
    "working", "used", "use", "using", "implemented", "implement", "handled", "handle", "handles", "repo",
    "repository", "project", "codebase", "code", "app", "application", "happen", "happens", "if", "then", "so",
    "get", "gets", "has", "have", "he", "she", "they", "than", "also", "much", "many", "some", "most", "default",
    "def", "self", "return", "import", "none", "true", "false", "new",
}


def split_identifier(word: str) -> list[str]:
    """snake_case and camelCase -> lowercase parts."""
    parts: list[str] = []
    for piece in word.split("_"):
        if not piece:
            continue
        parts.extend(m.group(0).lower() for m in _CAMEL.finditer(piece))
    return parts


def tokenize(text: str) -> list[str]:
    """Identifier-aware tokens: keeps the whole identifier AND its sub-words."""
    out: list[str] = []
    for m in _IDENT.finditer(text):
        word = m.group(0)
        low = word.lower()
        parts = split_identifier(word)
        if len(parts) > 1:
            out.append(low)
            out.extend(parts)
        else:
            out.append(low)
    return [t for t in out if len(t) > 1]


def stem(t: str) -> str:
    """Tiny consistent normaliser (tests/testing -> test, classes -> class, parse/parsed/parsing -> pars).

    Not linguistically correct - it only has to map related forms to the same key on BOTH sides.
    """
    if len(t) < 4:
        return t
    if t.endswith("ies"):
        t = t[:-3] + "y"
    elif not t.endswith("ss") and t.endswith("s"):
        t = t[:-1]
    if t.endswith("ing") and len(t) > 5:
        t = t[:-3]
    elif t.endswith("ed") and len(t) > 4:
        t = t[:-2]
    if t.endswith("e") and len(t) > 3:
        t = t[:-1]
    return t


def search_tokens(text: str) -> list[str]:
    """Tokens used to build the BM25 index (identifier-aware, stemmed)."""
    return [stem(t) for t in tokenize(text)]


def query_tokens(text: str) -> list[str]:
    """Tokens used to query BM25: filler words removed, then stemmed."""
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS]


def content_terms(question: str) -> list[str]:
    """The informative words of a question (used for coverage / abstain)."""
    seen: list[str] = []
    for t in tokenize(question):
        if t in STOPWORDS or len(t) < 3:
            continue
        if t not in seen:
            seen.append(t)
    return seen


def fuzzy_match(term: str, vocab_by_prefix: set[str]) -> bool:
    """True if `term` shares a >=4 char prefix (or exact) with any vocab token.

    Handles auth/authentication, user/users, token/tokens.
    """
    if term in vocab_by_prefix:
        return True
    n = min(5, len(term))
    if n < 4:
        return False
    key = term[:n]
    return any(v.startswith(key) or (len(v) >= 4 and term.startswith(v[: min(5, len(v))])) for v in vocab_by_prefix)
