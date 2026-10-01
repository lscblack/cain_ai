"""AI provider abstraction (OpenAI-compatible / OpenRouter).

The analyst is an analysis layer, not a source of truth. The system continues
to function without it: if no key is configured, get_ai_provider() returns None
and callers surface AI_UNAVAILABLE.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings


@dataclass
class AIMessage:
    role: str
    content: str


class AIProvider:
    name = "ai"

    def available(self) -> bool:
        raise NotImplementedError

    async def chat(self, messages: list[AIMessage], *, temperature: float = 0.2) -> str:
        raise NotImplementedError


class OpenAICompatibleProvider(AIProvider):
    """Works with OpenAI and OpenRouter (OpenAI-compatible) endpoints."""

    def __init__(self) -> None:
        s = get_settings()
        if s.openrouter_api_key:
            self.name = "openrouter"
            self._key = s.openrouter_api_key
            self._base = "https://openrouter.ai/api/v1"
        elif s.openai_api_key:
            self.name = "openai"
            self._key = s.openai_api_key
            self._base = s.openai_base_url
        else:
            self.name = "ai"
            self._key = ""
            self._base = s.openai_base_url
        self._model = s.ai_model

    def available(self) -> bool:
        return bool(self._key)

    async def chat(self, messages: list[AIMessage], *, temperature: float = 0.2) -> str:
        if not self._key:
            raise RuntimeError("ai_unavailable")
        import httpx

        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


_provider: AIProvider | None = None


def get_ai_provider() -> AIProvider | None:
    global _provider
    if _provider is None:
        p = OpenAICompatibleProvider()
        _provider = p
    return _provider if _provider.available() else None
