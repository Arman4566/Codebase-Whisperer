"""Thin OpenAI client over plain HTTPS (requests). Tracks token usage so the $50 budget is visible."""
from __future__ import annotations

import json
import time
from typing import Any

import requests

from .config import Settings

# USD per 1M tokens (input, output) - approximate public prices, used only for the budget meter.
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4.1-mini": (0.40, 1.60), "gpt-4o": (2.50, 10.0), "gpt-4.1": (2.0, 8.0),
          "text-embedding-3-small": (0.02, 0.0), "text-embedding-3-large": (0.13, 0.0)}


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, settings: Settings):
        self.s = settings
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "embedding_tokens": 0, "calls": 0}

    @property
    def available(self) -> bool:
        return self.s.has_llm

    # ---------------------------------------------------------------- http
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise LLMError("OPENAI_API_KEY is not set")
        url = self.s.openai_base_url.rstrip("/") + path
        headers = {"Authorization": f"Bearer {self.s.openai_api_key}", "Content-Type": "application/json"}
        last = ""
        for attempt in range(4):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=90)
            except requests.RequestException as e:
                last = str(e)
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 200:
                self.usage["calls"] += 1
                return r.json()
            last = f"{r.status_code}: {r.text[:300]}"
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            break
        raise LLMError(last)

    # ---------------------------------------------------------------- chat
    def chat(self, system: str, user: str, *, json_mode: bool = False, model: str | None = None,
             temperature: float = 0.1, max_tokens: int = 1800) -> str:
        payload: dict[str, Any] = {
            "model": model or self.s.chat_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post("/chat/completions", payload)
        u = data.get("usage", {})
        self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += u.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"] or ""

    def chat_json(self, system: str, user: str, **kw) -> dict[str, Any]:
        raw = self.chat(system, user, json_mode=True, **kw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMError(f"model returned invalid JSON: {e}") from e

    # ---------------------------------------------------------------- embeddings
    def embed(self, texts: list[str], batch: int = 64) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), batch):
            part = [t[:6000] or " " for t in texts[i : i + batch]]
            data = self._post("/embeddings", {"model": self.s.embed_model, "input": part})
            self.usage["embedding_tokens"] += data.get("usage", {}).get("total_tokens", 0)
            out.extend(d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"]))
        return out

    # ---------------------------------------------------------------- budget meter
    def cost_estimate(self) -> float:
        cin, cout = PRICES.get(self.s.chat_model, (0.5, 1.5))
        ein, _ = PRICES.get(self.s.embed_model, (0.02, 0.0))
        return round(self.usage["prompt_tokens"] / 1e6 * cin + self.usage["completion_tokens"] / 1e6 * cout
                     + self.usage["embedding_tokens"] / 1e6 * ein, 4)
