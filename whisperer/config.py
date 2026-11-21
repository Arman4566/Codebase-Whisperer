"""Runtime settings, read from environment variables (and a .env file if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv is optional
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("WHISPERER_DATA", ROOT / "data")))
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    chat_model: str = field(default_factory=lambda: os.environ.get("WHISPERER_CHAT_MODEL", "gpt-4o-mini"))
    embed_model: str = field(default_factory=lambda: os.environ.get("WHISPERER_EMBED_MODEL", "text-embedding-3-small"))
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""))
    # Safety valve: when false, approved actions are recorded but NOT sent to GitHub.
    allow_github_writes: bool = field(default_factory=lambda: os.environ.get("WHISPERER_ALLOW_GITHUB_WRITES", "0") == "1")
    max_chunk_lines: int = 120
    top_k: int = 8

    @property
    def has_llm(self) -> bool:
        return bool(self.openai_api_key)

    def ensure_dirs(self) -> None:
        try:
            (self.data_dir / "repos").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            # e.g. WHISPERER_DATA=/var/data without a mounted disk: keep running, but on temporary storage
            import sys
            import tempfile
            fallback = Path(tempfile.gettempdir()) / "whisperer-data"
            print(f"WARNING: cannot use data dir {self.data_dir} ({e}); using {fallback} (not persistent)", file=sys.stderr)
            self.data_dir = fallback
            (self.data_dir / "repos").mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
