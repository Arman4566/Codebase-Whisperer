from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Chunk:
    repo: str
    kind: str  # code | doc | config | commit | issue
    path: str  # file path, or "commit:<sha7>" / "issue#<n>" for pseudo-sources
    start_line: int
    end_line: int
    symbol: str
    language: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.repo}|{self.path}|{self.start_line}|{self.end_line}|{self.symbol}".encode()).hexdigest()[:16]

    @property
    def ref(self) -> str:
        """Citation string, e.g. src/auth.py:L10-L42 (pseudo-sources have no lines)."""
        if self.kind in ("commit", "issue"):
            return self.path
        return f"{self.path}:L{self.start_line}-L{self.end_line}"

    @property
    def search_text(self) -> str:
        return f"{self.path}\n{self.symbol}\n{self.text}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha1(self.search_text.encode("utf-8", "ignore")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Chunk":
        return cls(**d)

    def brief(self, max_chars: int = 600) -> dict[str, Any]:
        return {
            "id": self.id,
            "ref": self.ref,
            "kind": self.kind,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "symbol": self.symbol,
            "language": self.language,
            "snippet": self.text[:max_chars],
        }
