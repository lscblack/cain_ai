"""Orchestrator loop: JSON extraction, history trimming, and the full
model→tool→model turn driven by a deterministic fake provider (no slow model)."""
from __future__ import annotations

import json
import uuid

import pytest

from app.ai.ollama import OllamaModelMissing
from app.ai.router import AIMessage
from app.security import orchestrator as orch


class FakeProvider:
    """Streams scripted replies in order (one per call); optionally raises."""

    def __init__(self, replies, *, raise_exc=None):
        self._replies = list(replies)
        self._raise = raise_exc

    async def chat_stream(self, messages, *, params=None):
        if self._raise:
            raise self._raise
        reply = self._replies.pop(0)
        # emit in a couple of chunks to exercise streaming assembly
        mid = max(1, len(reply) // 2)
        for piece in (reply[:mid], reply[mid:]):
            if piece:
                yield piece


def test_extract_json_variants():
    assert orch.extract_json('{"action":"final","answer":"hi"}')["answer"] == "hi"
    fenced = 'Sure!\n```json\n{"action":"tool","operation":"dns.records","params":{"domain":"x.com"}}\n```'
    assert orch.extract_json(fenced)["operation"] == "dns.records"
    nested = 'noise {"a":{"b":1},"action":"final"} trailing'
    assert orch.extract_json(nested)["action"] == "final"
    assert orch.extract_json("no json here") is None


def test_trim_history_keeps_system_and_recent():
    sys = AIMessage(role="system", content="SYS")
    msgs = [sys] + [AIMessage(role="user", content="x" * 1000) for _ in range(500)]
    trimmed = orch.trim_history(msgs)
    assert trimmed[0].content == "SYS"
    assert len(trimmed) < len(msgs)  # dropped oldest


async def _drain(gen):
    return [e async for e in gen]


async def test_stream_decision_strips_leading_think_prose():
    """A <think> block before a prose answer must not leak to the operator and
    must not flip the turn into 'json' mode."""
    reply = "<think>let me reason about this</think>Here is the answer."
    prov = FakeProvider([reply])
    events = await _drain(orch._stream_decision(prov, [], None))
    result = events[-1][1]
    assert result["mode"] == "prose"
    assert result["visible"] == "Here is the answer."
    tokens = "".join(t for kind, t in events[:-1] if kind == "token")
    assert tokens == "Here is the answer."
    assert "think" not in tokens


async def test_stream_decision_strips_leading_think_tool_call():
    """A <think> block before a tool-call JSON must still be parsed as a tool."""
    reply = '<think>I should check DNS</think>{"action":"tool","operation":"dns.records","params":{"domain":"x.com"}}'
    prov = FakeProvider([reply])
    events = await _drain(orch._stream_decision(prov, [], None))
    result = events[-1][1]
    assert result["mode"] == "json"
    assert result["json"]["operation"] == "dns.records"
    # nothing streamed to the operator for a tool call
    assert not [t for kind, t in events[:-1] if kind == "token"]


async def test_run_turn_simple_final_persists_finding(db_session):
    uid = uuid.uuid4()
    final = json.dumps({
        "action": "final",
        "answer": "No issues observed.",
        "findings": [{
            "title": "Missing HSTS header", "severity": "low", "confidence": "suspected",
            "status": "suspected", "asset": "example.com", "tool": "curl",
            "evidence": ["no Strict-Transport-Security in response"],
        }],
    })
    events = await _drain(orch.run_turn(
        db_session, user_id=uid, conversation_id=None,
        history=[AIMessage(role="user", content="check example.com headers")],
        provider=FakeProvider([final]),
    ))
    final_ev = [e for e in events if e["type"] == "final"][0]
    assert final_ev["answer"] == "No issues observed."
    assert final_ev["findings"][0]["title"] == "Missing HSTS header"
    # persisted
    from app.database.models.security import SecurityFinding
    from sqlalchemy import select
    rows = (await db_session.execute(select(SecurityFinding).where(SecurityFinding.user_id == uid))).scalars().all()
    assert len(rows) == 1 and rows[0].severity == "low"


async def test_run_turn_executes_tool_then_answers(db_session, monkeypatch):
    uid = uuid.uuid4()
    canned = {"ok": True, "status": "ok", "stdout": "example.com. 300 IN A 93.184.216.34",
              "tool": "dig", "operation": "dns.records", "execution_id": "x"}

    async def fake_run_operation(session, **kw):
        assert kw["op_key"] == "dns.records"
        return canned

    monkeypatch.setattr(orch.service, "run_operation", fake_run_operation)

    tool_reply = json.dumps({"action": "tool", "operation": "dns.records", "params": {"domain": "example.com"}})
    final_reply = json.dumps({"action": "final", "answer": "A record is 93.184.216.34.", "findings": []})

    events = await _drain(orch.run_turn(
        db_session, user_id=uid, conversation_id=None,
        history=[AIMessage(role="user", content="resolve example.com")],
        provider=FakeProvider([tool_reply, final_reply]),
    ))
    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    tr = [e for e in events if e["type"] == "tool_result"][0]
    assert tr["result"]["stdout"].startswith("example.com")
    final_ev = [e for e in events if e["type"] == "final"][0]
    assert "93.184.216.34" in final_ev["answer"]
    assert len(final_ev["tool_calls"]) == 1


async def test_run_turn_tool_budget_forces_final(db_session, monkeypatch):
    uid = uuid.uuid4()

    async def fake_run_operation(session, **kw):
        return {"ok": True, "status": "ok", "stdout": "ok", "tool": "dig", "operation": kw["op_key"]}

    monkeypatch.setattr(orch.service, "run_operation", fake_run_operation)
    tool_reply = json.dumps({"action": "tool", "operation": "dns.records", "params": {"domain": "example.com"}})
    # Always asks for a tool; after budget the orchestrator forces a final prompt.
    replies = [tool_reply] * 20 + ["I could not finish within the tool budget."]

    events = await _drain(orch.run_turn(
        db_session, user_id=uid, conversation_id=None,
        history=[AIMessage(role="user", content="loop")],
        provider=FakeProvider(replies),
    ))
    final_ev = [e for e in events if e["type"] == "final"][0]
    assert final_ev["answer"]
    # Did not exceed the configured step budget.
    from app.core.config import get_settings
    assert len([e for e in events if e["type"] == "tool_call"]) <= get_settings().tool_max_agent_steps


async def test_run_turn_surfaces_model_error(db_session):
    events = await _drain(orch.run_turn(
        db_session, user_id=uuid.uuid4(), conversation_id=None,
        history=[AIMessage(role="user", content="hi")],
        provider=FakeProvider([], raise_exc=OllamaModelMissing("model kai-security not found")),
    ))
    err = [e for e in events if e["type"] == "error"][0]
    assert err["code"] == "ollama_model_missing"


async def test_run_turn_agent_blocks_tool_outside_allowlist(db_session, monkeypatch):
    from app.security.agents.profiles import PROFILES

    ran = []

    async def fake_run_operation(session, **kw):
        ran.append(kw["op_key"])
        return {"ok": True, "status": "ok", "stdout": "x", "operation": kw["op_key"]}

    monkeypatch.setattr(orch.service, "run_operation", fake_run_operation)
    tool_reply = json.dumps({"action": "tool", "operation": "shell.run", "params": {"command": "id"}})
    final_reply = json.dumps({"action": "final", "answer": "done", "findings": []})

    events = await _drain(orch.run_turn(
        db_session, user_id=uuid.uuid4(), conversation_id=None,
        history=[AIMessage(role="user", content="run id")],
        provider=FakeProvider([tool_reply, final_reply]),
        agent=PROFILES["web_research"],
    ))
    denied = [e for e in events if e["type"] == "tool_denied"]
    assert denied and denied[0]["operation"] == "shell.run"
    assert not [e for e in events if e["type"] == "tool_call" and e["operation"] == "shell.run"]
    assert ran == []


async def test_run_turn_agent_allows_tool_inside_allowlist(db_session, monkeypatch):
    from app.security.agents.profiles import PROFILES

    async def fake_run_operation(session, **kw):
        assert kw["op_key"] == "web.search"
        return {"ok": True, "status": "ok", "stdout": "results", "operation": "web.search"}

    monkeypatch.setattr(orch.service, "run_operation", fake_run_operation)
    tool_reply = json.dumps({"action": "tool", "operation": "web.search", "params": {"query": "kai"}})
    final_reply = json.dumps({"action": "final", "answer": "done", "findings": []})

    events = await _drain(orch.run_turn(
        db_session, user_id=uuid.uuid4(), conversation_id=None,
        history=[AIMessage(role="user", content="search kai")],
        provider=FakeProvider([tool_reply, final_reply]),
        agent=PROFILES["web_research"],
    ))
    assert [e for e in events if e["type"] == "tool_call" and e["operation"] == "web.search"]
    assert not [e for e in events if e["type"] == "tool_denied"]
