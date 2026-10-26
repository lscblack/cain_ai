"""Ollama chat provider for the local KAI security model.

Talks to a local Ollama server's real HTTP API (``/api/chat``, ``/api/tags``,
``/api/show``). The configured model (``KAI_OLLAMA_MODEL``, default
``kai-security``) is the only model this provider will use — KAI never silently
switches to a cloud model when it is unavailable. Instead the status surfaces
exactly what is wrong (server unreachable / model not installed) and the chat
calls raise typed errors the API layer turns into clear messages.

An ``httpx.AsyncClient`` can be injected so unit tests stay offline; the live
integration tests hit the real server when it is running.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

from app.ai.router import AIMessage
from app.core.config import get_settings


class OllamaError(RuntimeError):
    """Base class for all Ollama-related failures (carries a machine code)."""

    code = "ollama_error"


class OllamaUnreachable(OllamaError):
    code = "ollama_unreachable"


class OllamaModelMissing(OllamaError):
    code = "ollama_model_missing"


class OllamaTimeout(OllamaError):
    code = "ollama_timeout"


class OllamaBadResponse(OllamaError):
    code = "ollama_bad_response"


@dataclass
class OllamaStatus:
    endpoint: str
    model: str
    reachable: bool
    model_installed: bool
    models_available: list[str] = field(default_factory=list)
    error: str | None = None
    backend: str = "ollama"            # "ollama" | "llamacpp"
    accelerator: str | None = None     # e.g. "GPU (CUDA) · 37/37 layers" or "CPU"

    def to_dict(self) -> dict:
        return {
            "endpoint": self.endpoint,
            "model": self.model,
            "reachable": self.reachable,
            "model_installed": self.model_installed,
            "models_available": self.models_available,
            "error": self.error,
            "backend": self.backend,
            "accelerator": self.accelerator,
            # A single convenience flag the UI can gate on.
            "ready": self.reachable and self.model_installed,
        }


@dataclass
class GenParams:
    """Generation parameters; all optional, defaulting from settings."""

    temperature: float | None = None
    num_ctx: int | None = None
    top_p: float | None = None
    num_predict: int | None = None  # max tokens to generate (-1 = until stop)

    def to_options(self) -> dict:
        s = get_settings()
        opts: dict = {
            "temperature": self.temperature if self.temperature is not None else s.kai_ollama_temperature,
            "num_ctx": self.num_ctx if self.num_ctx is not None else s.kai_ollama_num_ctx,
        }
        if self.top_p is not None:
            opts["top_p"] = self.top_p
        if self.num_predict is not None:
            opts["num_predict"] = self.num_predict
        return opts


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.ollama_base_url).rstrip("/")
        self.model = model or s.kai_ollama_model
        self._timeout = s.kai_ollama_timeout_s
        self._client = client  # injected (tests); otherwise created per-call

    # ----- transport ---------------------------------------------------- #
    def _new_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout)

    async def _maybe_close(self, client: httpx.AsyncClient) -> None:
        if self._client is None:
            await client.aclose()

    # ----- status ------------------------------------------------------- #
    async def list_models(self) -> list[str]:
        client = self._new_client()
        try:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except httpx.TimeoutException as exc:
            raise OllamaTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise OllamaUnreachable(str(exc)) from exc
        finally:
            await self._maybe_close(client)

    def _model_present(self, models: list[str]) -> bool:
        # Ollama reports names with an explicit tag ("kai-security:latest").
        # Treat a bare configured name as matching its ":latest" tag.
        wanted = {self.model, f"{self.model}:latest"}
        if ":" in self.model:
            wanted.add(self.model.split(":", 1)[0])
        return any(m in wanted or m.split(":", 1)[0] == self.model.split(":", 1)[0] for m in models)

    async def status(self) -> OllamaStatus:
        try:
            models = await self.list_models()
        except OllamaError as exc:
            return OllamaStatus(
                endpoint=self.base_url,
                model=self.model,
                reachable=False,
                model_installed=False,
                error=f"{exc.code}: {exc}",
            )
        return OllamaStatus(
            endpoint=self.base_url,
            model=self.model,
            reachable=True,
            model_installed=self._model_present(models),
            models_available=models,
        )

    def available(self) -> bool:  # AIProvider-compatible (best-effort, sync-less)
        return True

    # ----- chat --------------------------------------------------------- #
    def _payload(self, messages: list[AIMessage], params: GenParams, *, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "options": params.to_options(),
            "keep_alive": "10m",
            # Disable "thinking" for hybrid reasoning models (e.g. Qwen3). KAI's
            # orchestration relies on the FIRST non-whitespace char to decide
            # tool-call JSON vs prose; a leading <think> block would break that,
            # and on CPU the reasoning tokens cost minutes per turn. Ollama
            # ignores this for non-thinking models (dolphin, llama3).
            "think": False,
        }

    @staticmethod
    def _raise_for_model(resp: httpx.Response) -> None:
        if resp.status_code == 404:
            raise OllamaModelMissing(_err_text(resp))
        if resp.status_code >= 400:
            raise OllamaBadResponse(f"http {resp.status_code}: {_err_text(resp)}")

    async def chat(self, messages: list[AIMessage], *, params: GenParams | None = None) -> str:
        params = params or GenParams()
        client = self._new_client()
        try:
            resp = await client.post("/api/chat", json=self._payload(messages, params, stream=False))
            self._raise_for_model(resp)
            data = resp.json()
            msg = (data or {}).get("message") or {}
            content = msg.get("content")
            if not isinstance(content, str):
                raise OllamaBadResponse("missing message.content in response")
            return content
        except httpx.TimeoutException as exc:
            raise OllamaTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise OllamaUnreachable(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise OllamaBadResponse(str(exc)) from exc
        finally:
            await self._maybe_close(client)

    async def chat_stream(
        self, messages: list[AIMessage], *, params: GenParams | None = None
    ) -> AsyncIterator[str]:
        """Yield content chunks as they arrive. Stops when the caller stops
        iterating (which closes the HTTP response) — that is how generation is
        cancelled. Raises the same typed errors as :meth:`chat`."""
        params = params or GenParams()
        client = self._new_client()
        try:
            async with client.stream(
                "POST", "/api/chat", json=self._payload(messages, params, stream=True)
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    self._raise_for_model(resp)
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise OllamaBadResponse(str(exc)) from exc
                    if obj.get("error"):
                        raise OllamaBadResponse(str(obj["error"]))
                    chunk = (obj.get("message") or {}).get("content") or ""
                    if chunk:
                        yield chunk
                    if obj.get("done"):
                        break
        except httpx.TimeoutException as exc:
            raise OllamaTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise OllamaUnreachable(str(exc)) from exc
        finally:
            await self._maybe_close(client)


def _err_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
    except Exception:  # noqa: BLE001
        pass
    return (resp.text or "").strip()[:300] or f"http {resp.status_code}"


_provider: OllamaProvider | None = None


def get_ollama_provider() -> OllamaProvider:
    """Process-wide chat provider for the selected backend (KAI_LLM_BACKEND:
    ``llamacpp`` or ``ollama``). Named for history; both share one interface."""
    global _provider
    if _provider is None:
        if get_settings().kai_llm_backend.lower() in ("llamacpp", "llama.cpp", "llama-cpp"):
            from app.ai.llamacpp import LlamaCppProvider

            _provider = LlamaCppProvider()
        else:
            _provider = OllamaProvider()
    return _provider
