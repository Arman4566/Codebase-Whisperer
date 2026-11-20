import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from whisperer.agent import Whisperer  # noqa: E402
from whisperer.config import Settings  # noqa: E402
from whisperer.llm import LLM, LLMError  # noqa: E402


class FakeLLM(LLM):
    """Deterministic stand-in for OpenAI: lets tests exercise the LLM answer path offline."""

    def __init__(self, settings, reply=None):
        super().__init__(settings)
        self.reply = reply or {}

    @property
    def available(self):
        return True

    def embed(self, texts, batch=64):
        # Simulates an embeddings outage: the index must degrade to the local backend, not crash.
        raise LLMError("embeddings unavailable in tests")

    def chat_json(self, system, user, **kw):
        return self.reply

    def chat(self, system, user, **kw):
        return "stub summary"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


@pytest.fixture()
def repo_copy(tmp_path):
    """A fresh writable copy of the sample repo (with its git history)."""
    dest = tmp_path / "tinyshop"
    shutil.copytree(ROOT / "sample_repo", dest)
    return dest


@pytest.fixture()
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", openai_api_key="")


@pytest.fixture()
def w(settings, repo_copy):
    wh = Whisperer(settings)
    wh.add_repo(str(repo_copy), "tinyshop")
    return wh
