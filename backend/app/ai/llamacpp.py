"""llama.cpp (``llama-server``) chat provider.

Same interface as :class:`OllamaProvider` (so the orchestrator, chat API and
status badge work unchanged) but talks to llama-server's OpenAI-compatible API
(``/v1/chat/completions``, ``/v1/models``, ``/health``). llama-server serves one
GGUF chosen at launch (``-m``), with GPU offload via ``-ngl``; this provider
reports honestly whether that server is up, still loading, and whether the
model is running on the GPU or the CPU.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from app.ai.ollama import (
    GenParams,
    OllamaBadResponse,
    OllamaError,
    OllamaModelMissing,
    OllamaProvider,
    OllamaStatus,
    OllamaTimeout,
    OllamaUnreachable,
    _err_text,
)
from app.ai.router import AIMessage
from app.core.config import get_settings


@dataclass
class _Server:
    """One llama-server instance (e.g. the CPU one, or the Intel-iGPU one)."""

    url: str
    weight: float           # relative speed: used to share new conversations
    log_path: str = ""
    inflight: int = 0
    down_until: float = 0.0

    @property
    def healthy(self) -> bool:
        return time.time() >= self.down_until


class LlamaCppProvider(OllamaProvider):
    """Talks to one or more llama-server instances running the same model on
    different hardware (CPU + Intel iGPU). Each *conversation* is pinned to one
    instance — so its prompt cache stays warm — and new conversations go to the
    least-loaded instance, so both chips work at the same time under load."""

    name = "llamacpp"

    def __init__(self, *, base_url: str | None = None, model: str | None = None,
                 client: httpx.AsyncClient | None = None) -> None:
        super().__init__(client=client)
        s = get_settings()
        self.base_url = (base_url or s.llamacpp_base_url).rstrip("/")
        self.model = model or s.kai_llamacpp_model
        self._log_path = s.llamacpp_log_path
        self._servers = [_Server(self.base_url, 1.0, s.llamacpp_log_path)]
        for i, extra in enumerate(u.strip() for u in s.llamacpp_extra_urls.split(",") if u.strip()):
            self._servers.append(_Server(extra.rstrip("/"), s.llamacpp_extra_weight,
                                         s.llamacpp_extra_log_paths.split(",")[i].strip()
                                         if s.llamacpp_extra_log_paths else ""))
        self._sticky: dict[str, tuple[_Server, float]] = {}

    # ----- multi-server routing ---------------------------------------- #
    def _client_for(self, srv: _Server) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(base_url=srv.url, timeout=self._timeout)

    def _pick(self, messages: list[AIMessage], exclude: set[int] | None = None) -> _Server | None:
        exclude = exclude or set()
        cands = [x for x in self._servers if x.healthy and id(x) not in exclude]
        if not cands:
            cands = [x for x in self._servers if id(x) not in exclude]
        if not cands:
            return None
        first_user = next((m.content for m in messages if m.role == "user"), "")
        key = hashlib.sha1(first_user[:2000].encode()).hexdigest()
        now = time.time()
        for k in [k for k, (_, t) in self._sticky.items() if now - t > 1800]:
            self._sticky.pop(k, None)
        hit = self._sticky.get(key)
        if hit and hit[0] in cands:
            self._sticky[key] = (hit[0], now)
            return hit[0]
        srv = min(cands, key=lambda x: (x.inflight + 1) / x.weight)
        self._sticky[key] = (srv, now)
        return srv

    # ----- status ------------------------------------------------------- #
    async def list_models(self) -> list[str]:
        client = self._new_client()
        try:
            resp = await client.get("/v1/models")
            resp.raise_for_status()
            data = resp.json()
            return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        except httpx.TimeoutException as exc:
            raise OllamaTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise OllamaUnreachable(str(exc)) from exc
        finally:
            await self._maybe_close(client)

    def _accelerator(self, path: str | None = None) -> str | None:
        """Read what llama-server logged at load time: GPU (CUDA) layers or CPU."""
        path = path if path is not None else self._log_path
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 400_000))
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            return None
        offloaded = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", text)
        if offloaded:
            n, total = offloaded[-1]
            if int(n) == 0:
                return "CPU"
            # e.g. "ggml_vulkan: 0 = Intel(R) UHD Graphics 770 (ADL-S GT1) (…) | uma: 1 …"
            #      "Device 0: NVIDIA GeForce RTX 4060, compute capability 8.9 …"
            m = (re.findall(r"using device \w+ \((.+)\) \([0-9a-f:.]+\)", text)
                 or re.findall(r"ggml_vulkan: \d+ = (.+?) \|", text)
                 or re.findall(r"Device \d+: (.+?),", text))
            name = m[-1].strip() if m else ""
            while True:  # drop trailing "(ADL-S GT1)" / "(… Mesa driver)" qualifiers
                short = re.sub(r"\s*\([^()]*\)\s*$", "", name)
                if short == name:
                    break
                name = short
            return f"GPU ({name}) · {n}/{total} layers" if name else f"GPU · {n}/{total} layers"
        if "no usable GPU found" in text or "CUDA error" in text or "failed to initialize CUDA" in text:
            return "CPU (GPU unavailable)"
        return "CPU"

    async def status(self) -> OllamaStatus:
        client = self._new_client()
        try:
            try:
                h = await client.get("/health")
            except httpx.HTTPError as exc:
                return OllamaStatus(endpoint=self.base_url, model=self.model, reachable=False,
                                    model_installed=False, backend="llamacpp",
                                    error=f"llamacpp_unreachable: {exc}")
            if h.status_code == 503:
                return OllamaStatus(endpoint=self.base_url, model=self.model, reachable=True,
                                    model_installed=False, backend="llamacpp",
                                    error="llama.cpp is still loading the model — try again in a moment")
            if h.status_code >= 400:
                return OllamaStatus(endpoint=self.base_url, model=self.model, reachable=True,
                                    model_installed=False, backend="llamacpp",
                                    error=f"llama.cpp health check failed: http {h.status_code}")
        finally:
            await self._maybe_close(client)
        try:
            models = await self.list_models()
        except OllamaError:
            models = [self.model]
        accel = self._accelerator()
        # additional instances (other hardware) → "CPU + GPU (…)"
        for extra in self._servers[1:]:
            try:
                async with httpx.AsyncClient(base_url=extra.url, timeout=3) as c:
                    ok = (await c.get("/health")).status_code == 200
            except httpx.HTTPError:
                ok = False
            if ok:
                accel = f"{accel or 'CPU'} + {self._accelerator(extra.log_path) or 'GPU'}"
        return OllamaStatus(endpoint=self.base_url, model=self.model, reachable=True,
                            model_installed=True, models_available=models,
                            backend="llamacpp", accelerator=accel)

    # ----- chat --------------------------------------------------------- #
    def _payload(self, messages: list[AIMessage], params: GenParams, *, stream: bool) -> dict:
        s = get_settings()
        body: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "temperature": params.temperature if params.temperature is not None else s.kai_ollama_temperature,
            "cache_prompt": True,
            # Hybrid reasoning models (Qwen3): no <think> block — KAI's tool
            # protocol reads the first character of the reply (see OllamaProvider).
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if params.top_p is not None:
            body["top_p"] = params.top_p
        if params.num_predict is not None and params.num_predict > 0:
            body["max_tokens"] = params.num_predict
        return body

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.status_code == 503:
            raise OllamaUnreachable("llama.cpp is still loading the model")
        if resp.status_code == 404:
            raise OllamaModelMissing(_err_text(resp))
        if resp.status_code >= 400:
            raise OllamaBadResponse(f"http {resp.status_code}: {_err_text(resp)}")

    async def chat(self, messages: list[AIMessage], *, params: GenParams | None = None) -> str:
        params = params or GenParams()
        tried: set[int] = set()
        while True:
            srv = self._pick(messages, tried)
            if srv is None:
                raise OllamaUnreachable("no llama.cpp server available")
            tried.add(id(srv))
            srv.inflight += 1
            client = self._client_for(srv)
            try:
                resp = await client.post("/v1/chat/completions",
                                         json=self._payload(messages, params, stream=False))
                self._raise_for(resp)
                data = resp.json()
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                if not isinstance(content, str):
                    raise OllamaBadResponse("missing choices[0].message.content in response")
                return _strip_think(content)
            except httpx.TimeoutException as exc:
                raise OllamaTimeout(str(exc)) from exc
            except (httpx.HTTPError, OllamaUnreachable) as exc:
                srv.down_until = time.time() + 30
                if len(tried) < len(self._servers):
                    continue  # fail over to the other chip
                raise (exc if isinstance(exc, OllamaUnreachable) else OllamaUnreachable(str(exc))) from exc
            finally:
                srv.inflight -= 1
                await self._maybe_close(client)

    async def chat_stream(self, messages: list[AIMessage], *,
                          params: GenParams | None = None) -> AsyncIterator[str]:
        params = params or GenParams()
        tried: set[int] = set()
        while True:
            srv = self._pick(messages, tried)
            if srv is None:
                raise OllamaUnreachable("no llama.cpp server available")
            tried.add(id(srv))
            srv.inflight += 1
            client = self._client_for(srv)
            in_think = False
            started = False
            try:
                async with client.stream("POST", "/v1/chat/completions",
                                         json=self._payload(messages, params, stream=True)) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        self._raise_for(resp)
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError as exc:
                            raise OllamaBadResponse(str(exc)) from exc
                        if obj.get("error"):
                            raise OllamaBadResponse(str(obj["error"]))
                        delta = ((obj.get("choices") or [{}])[0].get("delta") or {})
                        chunk = delta.get("content") or ""
                        # Defensive: drop any <think>…</think> a template still emits.
                        if "<think>" in chunk:
                            in_think = True
                        if in_think:
                            if "</think>" in chunk:
                                in_think = False
                                chunk = chunk.split("</think>", 1)[1].lstrip("\n")
                            else:
                                continue
                        if chunk:
                            started = True
                            yield chunk
                return
            except httpx.TimeoutException as exc:
                raise OllamaTimeout(str(exc)) from exc
            except (httpx.HTTPError, OllamaUnreachable) as exc:
                srv.down_until = time.time() + 30
                if not started and len(tried) < len(self._servers):
                    continue  # nothing sent yet: fail over to the other chip
                raise (exc if isinstance(exc, OllamaUnreachable) else OllamaUnreachable(str(exc))) from exc
            finally:
                srv.inflight -= 1
                await self._maybe_close(client)


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S).lstrip()
