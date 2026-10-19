"""Model → tool orchestration.

The ``kai-security`` model has only the ``completion`` capability (no native
Ollama tool-calling), so we DO NOT pretend tool calls happened. Instead we run
a validated backend orchestration:

1. We hand the model a strict JSON protocol and the catalogue of real, installed
   operations.
2. The model replies with a single JSON object: either a tool request or a
   final answer.
3. The backend validates and executes a tool request through the hardened
   service (argv, auth, limits, audit), feeds the REAL result back, and asks
   again — up to a bounded number of steps.
4. The final answer (and any structured findings) is grounded in actual output.

The whole turn is streamed to the UI as SSE-style events.
"""
from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ollama import GenParams, OllamaError, OllamaProvider
from app.ai.router import AIMessage
from app.core.config import get_settings
from app.security import registry, service

FINDING_FIELDS = (
    "title", "description", "severity", "confidence", "status", "asset",
    "tool", "evidence", "impact", "remediation", "validation", "limitations",
)


import time as _time

_CATALOGUE_CACHE: tuple[float, str] | None = None
_CATALOGUE_TTL = 120.0  # seconds


async def build_catalogue(force: bool = False) -> str:
    """Operations the model may call. To keep the (slow) model's prompt small,
    we list only INSTALLED tools' operations and summarise the rest as
    installable. Cached briefly since host state changes rarely."""
    global _CATALOGUE_CACHE
    now = _time.monotonic()
    if not force and _CATALOGUE_CACHE and now - _CATALOGUE_CACHE[0] < _CATALOGUE_TTL:
        return _CATALOGUE_CACHE[1]

    # discover every tool once, in parallel
    tools = list(registry.ALL_TOOLS)
    import asyncio

    discs = await asyncio.gather(*(registry.discover(t) for t in tools))
    installed_names = {t.name for t, d in zip(tools, discs) if d.installed}
    missing_names = [t.name for t, d in zip(tools, discs) if not d.installed]

    lines: list[str] = []
    for tool, op in registry.all_operations():
        if tool.name not in installed_names:
            continue
        params = ", ".join(
            f"{p.name}" + ("" if p.required else f"[{p.default}]") for p in op.params
        ) or "(none)"
        auth = " [needs authorized target]" if op.requires_authorization else ""
        lines.append(f"- {op.key} ({op.posture}){auth}: {op.description} params: {params}")

    more = ""
    if missing_names:
        sample = ", ".join(sorted(missing_names)[:30])
        more = (
            f"\n\n{len(missing_names)} more OSINT/security tools can be installed on "
            f"request (e.g. {sample}). If one would help, tell the operator to install "
            f"its package via the approval workflow."
        )
    text = "Runnable operations (installed tools only):\n" + ("\n".join(lines) or "(none)") + more
    _CATALOGUE_CACHE = (now, text)
    return text


async def protocol_system_message(max_steps: int) -> AIMessage:
    catalogue = await build_catalogue()
    content = (
        "You are KAI operating in a security console with access to REAL host "
        "tools through a controlled backend. You never get a shell.\n\n"
        "TOOL PROTOCOL — follow exactly:\n"
        "• To run a tool, reply with ONLY a JSON object and no other text:\n"
        '  {\"action\":\"tool\",\"operation\":\"<operation key>\",\"params\":{...}}\n'
        f"• You may run at most {max_steps} tools, one per reply. After each you "
        "receive its real output as a tool message.\n"
        "• To ANSWER the operator, do NOT use JSON — just write your answer directly "
        "as markdown prose (it is streamed to them live). JSON is ONLY for tool calls.\n"
        "• If you have structured security findings, put them AFTER your prose answer "
        "inside ONE fenced block labelled findings, e.g.:\n"
        "  ```findings\n"
        '  [{\"title\":\"...\",\"severity\":\"medium\",\"confidence\":\"suspected\",'
        '\"status\":\"suspected\",\"asset\":\"...\",\"evidence\":[\"...\"],'
        '\"remediation\":\"...\"}]\n'
        "  ```\n"
        "  Each finding may include: title, description, severity (info|low|medium|"
        "high|critical), confidence (suspected|likely|confirmed), status (suspected|"
        "verified), asset, tool, evidence (list of strings), impact, remediation, "
        "validation, limitations.\n\n"
        "RULES:\n"
        "• Never invent or assume tool output. Only use what tools actually return.\n"
        "• If a needed tool is NOT INSTALLED, do not try to run it — produce a final "
        "answer telling the operator to install its package via the approval workflow.\n"
        "• Active operations require the target to be on the operator's authorized "
        "list; if a run is denied, say so and ask the operator to authorize it.\n"
        "• Distinguish a suspected issue from a verified finding; cite the tool and "
        "evidence for every claim.\n"
        "• For simple conversational questions, just write your answer directly.\n\n"
        "GUIDANCE:\n"
        "• For a website / domain security review, gather evidence from several "
        "passive tools before concluding — typically http.headers (missing "
        "security headers like HSTS/CSP/X-Frame-Options), tls.inspect "
        "(certificate + protocol), dns.records, and whois. Run them one per step, "
        "then summarise findings with severity and remediation.\n"
        "• http.headers and tls.inspect accept the site's URL/host; use the exact "
        "host the operator gave.\n\n"
        + catalogue
    )
    return AIMessage(role="system", content=content)


def extract_json(text: str) -> dict | None:
    """Pull the first balanced JSON object out of the model's reply."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : i + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict):
                                return obj
                        except json.JSONDecodeError:
                            break
        start = text.find("{", start + 1)
    return None


import re

_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.S)


def extract_findings(text: str) -> list:
    """Pull findings out of a fenced code block in a prose answer (best effort)."""
    if not text:
        return []
    for body in _FENCE_RE.findall(text):
        body = body.strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("findings"), list):
            return data["findings"]
    return []


async def _stream_decision(provider, messages, params):
    """Run one model turn as a stream. Decide early whether the reply is a tool
    call (JSON — buffered silently) or a prose answer (streamed live, with any
    trailing code fence hidden from the live view). Yields ("token", text) for
    visible prose and finally ("result", {...}). Propagates OllamaError."""
    buf = ""
    mode: str | None = None
    emitted = 0          # chars of prose already yielded
    fence_hit = False
    async for chunk in provider.chat_stream(messages, params=params):
        buf += chunk
        if mode is None:
            stripped = buf.lstrip()
            if not stripped:
                continue
            mode = "json" if stripped[0] == "{" else "prose"
        if mode == "prose" and not fence_hit:
            idx = buf.find("```")
            visible_end = idx if idx != -1 else len(buf)
            if idx != -1:
                fence_hit = True
            if visible_end > emitted:
                yield ("token", buf[emitted:visible_end])
                emitted = visible_end
    obj = extract_json(buf) if mode == "json" else None
    visible = buf[:emitted] if mode == "prose" else ""
    yield ("result", {"raw": buf, "json": obj, "mode": mode or "prose", "visible": visible})


def trim_history(messages: list[AIMessage]) -> list[AIMessage]:
    """Keep system messages + the most recent turns under the context budget."""
    s = get_settings()
    budget_chars = max(1000, (s.kai_ollama_num_ctx - 1024) * s.kai_ollama_chars_per_token)
    system = [m for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    used = sum(len(m.content) for m in system)
    kept: list[AIMessage] = []
    for m in reversed(rest):
        if used + len(m.content) > budget_chars:
            break
        kept.append(m)
        used += len(m.content)
    return system + list(reversed(kept))


async def _persist_findings(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID | None, findings: list
) -> list[dict]:
    from app.database.models.security import SecurityFinding

    out: list[dict] = []
    for f in findings or []:
        if not isinstance(f, dict) or not f.get("title"):
            continue
        row = SecurityFinding(
            user_id=user_id,
            conversation_id=conversation_id,
            title=str(f.get("title"))[:300],
            description=str(f.get("description", "")),
            severity=str(f.get("severity", "info")).lower()[:20],
            confidence=str(f.get("confidence", "suspected")).lower()[:20],
            status=str(f.get("status", "suspected")).lower()[:20],
            asset=(str(f.get("asset")) if f.get("asset") else None),
            tool=(str(f.get("tool")) if f.get("tool") else None),
            evidence=[str(e) for e in (f.get("evidence") or [])][:50],
            impact=str(f.get("impact", "")),
            remediation=str(f.get("remediation", "")),
            validation=str(f.get("validation", "")),
            limitations=str(f.get("limitations", "")),
        )
        session.add(row)
        await session.flush()
        d = {k: getattr(row, k) for k in FINDING_FIELDS}
        d["id"] = str(row.id)
        out.append(d)
    return out


async def run_turn(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    history: list[AIMessage],
    provider: OllamaProvider,
) -> AsyncIterator[dict]:
    """Drive one assistant turn, yielding SSE events. The final event carries
    the assistant's answer text, any tool calls made, and persisted findings."""
    s = get_settings()
    max_steps = s.tool_max_agent_steps
    sys_msg = await protocol_system_message(max_steps)
    convo = [sys_msg] + list(history)
    tool_calls_made: list[dict] = []
    params = GenParams(num_ctx=s.kai_ollama_num_ctx)

    for step in range(max_steps + 1):
        last_step = step == max_steps
        yield {"type": "thinking", "step": step}

        # Stream the decision; forward prose tokens live as they arrive.
        payload: dict = {}
        try:
            async for kind, data in _stream_decision(provider, trim_history(convo), params):
                if kind == "token":
                    yield {"type": "token", "text": data}
                else:
                    payload = data
        except OllamaError as exc:
            yield {"type": "error", "code": getattr(exc, "code", "ollama_error"), "message": str(exc)}
            return

        obj = payload.get("json")
        mode = payload.get("mode")
        action = (obj or {}).get("action") if obj else None

        # ── tool call (and we still have budget) ──
        if mode == "json" and action == "tool" and not last_step:
            op_key = str(obj.get("operation", ""))
            op_params = obj.get("params") or {}
            if not isinstance(op_params, dict):
                op_params = {}
            yield {"type": "tool_call", "operation": op_key, "params": op_params, "step": step}
            result = await service.run_operation(
                session, user_id=user_id, op_key=op_key, params=op_params,
                conversation_id=conversation_id,
            )
            tool_calls_made.append({"operation": op_key, "params": op_params, "result": _slim(result)})
            yield {"type": "tool_result", "operation": op_key, "result": _slim(result)}
            convo.append(AIMessage(role="assistant", content=json.dumps(
                {"action": "tool", "operation": op_key, "params": op_params})))
            convo.append(AIMessage(role="user", content=(
                "TOOL RESULT for " + op_key + ":\n" + _result_for_model(result))))
            continue

        # ── tool call but budget exhausted → force a final prose answer ──
        if mode == "json" and action == "tool" and last_step:
            convo.append(AIMessage(role="user", content=(
                "Tool budget reached. Write your final answer to the operator now "
                "as markdown prose (do not use JSON).")))
            try:
                async for kind, data in _stream_decision(provider, trim_history(convo), params):
                    if kind == "token":
                        yield {"type": "token", "text": data}
                    else:
                        payload = data
            except OllamaError as exc:
                yield {"type": "error", "code": getattr(exc, "code", "ollama_error"), "message": str(exc)}
                return
            obj = payload.get("json")
            mode = payload.get("mode")

        # ── final answer ──
        if mode == "prose":
            answer = (payload.get("visible") or "").strip()
            findings_in = extract_findings(payload.get("raw", ""))
            if not answer:
                answer = (payload.get("raw") or "").strip()
        elif obj is not None and obj.get("action") == "final":
            # Fallback: model used the old JSON final form (no live stream).
            answer = str(obj.get("answer", "")).strip()
            findings_in = obj.get("findings") or []
            if answer:
                yield {"type": "token", "text": answer}
        else:
            answer = (payload.get("visible") or payload.get("raw") or "").strip()
            findings_in = extract_findings(payload.get("raw", ""))
        if not answer:
            answer = "I reached the tool limit before I could fully answer."

        findings = await _persist_findings(session, user_id, conversation_id, findings_in)
        yield {"type": "final", "answer": answer, "tool_calls": tool_calls_made, "findings": findings}
        return


def _slim(result: dict) -> dict:
    """A compact result for the UI/history (keep output bounded)."""
    r = dict(result)
    for k in ("stdout", "stderr"):
        if isinstance(r.get(k), str) and len(r[k]) > 4000:
            r[k] = r[k][:4000] + "\n…[truncated]"
    return r


def _result_for_model(result: dict) -> str:
    keep = {k: result.get(k) for k in ("status", "ok", "exit_code", "tool", "operation", "error", "reason", "message")}
    text = json.dumps(keep)
    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    res = result.get("result")
    extra = ""
    if res is not None:
        extra = "\nRESULT_JSON:\n" + json.dumps(res)[:4000]
    return (
        text
        + ("\nSTDOUT:\n" + stdout[:4000] if stdout else "")
        + ("\nSTDERR:\n" + stderr[:1500] if stderr else "")
        + extra
    )
