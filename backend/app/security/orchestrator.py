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


async def build_catalogue() -> str:
    lines: list[str] = []
    installed: list[str] = []
    missing: list[str] = []
    seen_tools: dict[str, bool] = {}
    for tool, op in registry.all_operations():
        if tool.name not in seen_tools:
            disc = await registry.discover(tool)
            seen_tools[tool.name] = disc.installed
            (installed if disc.installed else missing).append(f"{tool.name}({tool.package})")
        avail = "installed" if seen_tools[tool.name] else "NOT INSTALLED"
        params = ", ".join(
            f"{p.name}" + ("" if p.required else f"[{p.default}]") for p in op.params
        ) or "(none)"
        auth = " [requires authorized target]" if op.requires_authorization else ""
        lines.append(
            f"- {op.key} ({op.posture}, {avail}){auth}: {op.description} "
            f"params: {params}"
        )
    return (
        "Available operations:\n" + "\n".join(lines)
        + "\n\nInstalled tools: " + (", ".join(sorted(set(installed))) or "none")
        + "\nMissing tools: " + (", ".join(sorted(set(missing))) or "none")
    )


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
        "• When you can answer, reply with ONLY this JSON object:\n"
        '  {\"action\":\"final\",\"answer\":\"<concise markdown grounded in the '
        'tool output>\",\"findings\":[]}\n'
        "• findings is optional; each item may have: title, description, severity "
        "(info|low|medium|high|critical), confidence (suspected|likely|confirmed), "
        "status (suspected|verified), asset, tool, evidence (list of strings), "
        "impact, remediation, validation, limitations.\n\n"
        "RULES:\n"
        "• Never invent or assume tool output. Only use what tools actually return.\n"
        "• If a needed tool is NOT INSTALLED, do not try to run it — produce a final "
        "answer telling the operator to install its package via the approval workflow.\n"
        "• Active operations require the target to be on the operator's authorized "
        "list; if a run is denied, say so and ask the operator to authorize it.\n"
        "• Distinguish a suspected issue from a verified finding; cite the tool and "
        "evidence for every claim.\n"
        "• For simple conversational questions, just answer with the final JSON.\n\n"
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
        try:
            raw = await provider.chat(trim_history(convo), params=params)
        except OllamaError as exc:
            yield {"type": "error", "code": getattr(exc, "code", "ollama_error"), "message": str(exc)}
            return

        obj = extract_json(raw)
        action = (obj or {}).get("action")

        # No/!tool JSON, or explicit final, or we've run out of tool budget.
        if not obj or action == "final" or (action == "tool" and last_step) or action not in ("tool", "final"):
            if action == "tool" and last_step:
                convo.append(AIMessage(role="user", content=(
                    "Tool budget exhausted. Provide your final answer now as the "
                    "final JSON object.")))
                try:
                    raw = await provider.chat(trim_history(convo), params=params)
                except OllamaError as exc:
                    yield {"type": "error", "code": getattr(exc, "code", "ollama_error"), "message": str(exc)}
                    return
                obj = extract_json(raw)

            answer = ""
            findings_in: list = []
            if obj and obj.get("action") == "final":
                answer = str(obj.get("answer", "")).strip()
                findings_in = obj.get("findings") or []
            if not answer:
                # Model replied in prose (or malformed JSON) — use it verbatim.
                answer = raw.strip()

            findings = await _persist_findings(session, user_id, conversation_id, findings_in)
            yield {"type": "final", "answer": answer, "tool_calls": tool_calls_made, "findings": findings}
            return

        # action == "tool"
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

        # Feed the model the real (redacted, trimmed) result.
        convo.append(AIMessage(role="assistant", content=json.dumps(
            {"action": "tool", "operation": op_key, "params": op_params})))
        convo.append(AIMessage(role="user", content=(
            "TOOL RESULT for " + op_key + ":\n" + _result_for_model(result))))


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
