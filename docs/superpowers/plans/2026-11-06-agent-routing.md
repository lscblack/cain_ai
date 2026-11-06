# KAI Agent Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route each chat message (or each decomposed subtask) to a narrow-toolset
specialist agent instead of letting the model pick from the whole tool catalogue, and
show the operator which agent ran and why.

**Architecture:** A new `backend/app/security/agents/` package holds six static agent
profiles (prompt + allowed operation keys + step budget) and a `route()` function that
classifies a message by rule first, model second. `run_turn` is extended to accept an
`agent` profile and enforces its `allowed_tools` server-side. `run_multi` becomes the
one path chat always uses; a single-subtask plan behaves like today's single turn.
`agent_selected` SSE events tell the frontend which agent ran; `ActionDeck`'s
Multi-agent toggle is replaced with an Agent selector (Auto + six agents + badge).

**Tech Stack:** FastAPI/SQLAlchemy async backend (Python), React/TypeScript frontend,
Ollama-backed local model via `app/ai/router.py`.

**Spec:** `docs/superpowers/specs/2026-11-06-agent-routing-design.md`

## Global Constraints

- Six agents only: Shell & Network, Web Research, Map & Geo, People & Identity,
  Investigations & Files, General (fallback).
- Rule classification must cost zero model tokens; the model is called only when rules
  are unsure, as one short call.
- A manual agent pick skips classification entirely.
- Multi-agent decomposition is always on — there is no on/off toggle anymore.
- An agent may never run an operation outside its `allowed_tools`, even if the model
  requests it — this must be enforced in `run_turn`, not just in the prompt.
- Shell & Network's system prompt must instruct it to report only what command output
  actually shows, and to say so explicitly when a command fails or returns nothing.
- `mode` field on `NewMessage` stays for backward compatibility and is ignored by the
  server; a new optional `agent` field carries a manual override.

## Review Focus

- **Ambiguous message** ("check example.com") that could fit either Shell & Network or
  Web Research: the rule scorer must produce a near-tie score, triggering the model
  fallback rather than silently guessing — tested in Task 1.
- **Model call fails or returns unparsable JSON during classification**: `route()` must
  fall back to General, not raise or hang the turn — tested in Task 1.
- **Model tries to call a tool outside its routed agent's `allowed_tools`** (e.g. Web
  Research agent emitting `shell.run`): `run_turn` must refuse it server-side and tell
  the model why, not just rely on the prompt — tested in Task 2.
- **Single-subtask plan from the planner** (objective needs no split): `run_multi` must
  behave exactly like one routed `run_turn` call, not emit an empty subtask wrapper —
  tested in Task 3.
- **Manual agent override while the message content clearly suggests a different
  agent**: the manual pick must win and `reason` must report `"manual"` — tested in
  Task 1 and re-verified end-to-end in Task 4.

---

## File Structure

- Create `backend/app/security/agents/__init__.py` — empty, makes the package.
- Create `backend/app/security/agents/profiles.py` — `AgentProfile` dataclass and the
  six static profiles plus a `PROFILES: dict[str, AgentProfile]` lookup.
- Create `backend/app/security/agents/router.py` — rule table, `score_rules()`,
  `route()`.
- Create `backend/tests/test_agent_router.py` — tests for `router.py`.
- Modify `backend/app/security/orchestrator.py` — `run_turn` gains `agent` param and
  tool-allowlist enforcement; `run_multi` always routes each subtask and emits
  `agent_selected`; single-subtask shortcut still routes once.
- Modify `backend/app/api/chat.py` — `NewMessage` gains `agent: str | None`; `_drive_turn`
  always calls `orchestrator.run_multi` and forwards `body.agent`.
- Modify `backend/tests/test_chat_api.py` — cover the new `agent` field and
  `agent_selected` event passthrough.
- Modify `frontend/src/lib/chat.ts` — `streamMessage` takes `agent?: string` instead of
  `mode`; `SseEvent`-handling callers gain an `agent_selected` case.
- Modify `frontend/src/components/chat/ActionDeck.tsx` — replace the Multi-agent toggle
  with an Agent selector.
- Modify `frontend/src/pages/Chat.tsx` — `LiveTurn` gains `agent` state; handle
  `agent_selected`; render an agent badge; drop `multi`/`onMultiChange` wiring.

---

### Task 1: Agent profiles and rule/model router

**Files:**
- Create: `backend/app/security/agents/__init__.py`
- Create: `backend/app/security/agents/profiles.py`
- Create: `backend/app/security/agents/router.py`
- Test: `backend/tests/test_agent_router.py`

**Interfaces:**
- Produces:
  - `AgentProfile` dataclass in `profiles.py`: fields `id: str`, `name: str`,
    `system_prompt: str`, `allowed_tools: frozenset[str]`, `max_steps: int`.
  - `PROFILES: dict[str, AgentProfile]` in `profiles.py`, keyed by `id`.
  - `AGENT_IDS: tuple[str, ...]` in `profiles.py` — `("shell_network", "web_research",
    "map_geo", "people_identity", "investigations_files", "general")`, in that order.
  - `route(message: str, history: list[AIMessage] | None = None, forced: str | None =
    None, model_classify: Callable[[str], Awaitable[str | None]] | None = None) ->
    RouteResult` in `router.py`, where
    `RouteResult = {"agent": str, "reason": Literal["rule","model","manual","fallback"],
    "confidence": float}`. `model_classify` defaults to a real one-shot model call built
    from `app.ai.router.AIMessage`/the chat provider when `None`, but tests inject a
    fake.

**Agent allowed_tools (exact operation keys), from the spec's roster:**
- `shell_network`: `shell.run`, `dns.records`, `whois.lookup`, `http.headers`,
  `tls.inspect`, `nmap.service_scan`, `logs.ssh_auth`, `firewall.status`, `cve.lookup`.
- `web_research`: `web.search`, `web.fetch` (the "open a URL" operation —
  confirm against `app.security.web.WEB_OPEN_OP_KEY`'s literal value and use that
  constant, not a hardcoded string, if it differs from `"web.fetch"`).
- `map_geo`: the `app.security.web.MAPS_FIND_OP_KEY` constant's value.
- `people_identity`: `app.security.service.IDENTITY_LOOKUP_OP_KEY`,
  `app.security.service.DATA_LOOKUP_OP_KEY`, plus `"people.investigate"`.
- `investigations_files`: `app.security.workspace.WRITE_OP_KEY`,
  `app.security.workspace.LIST_OP_KEY`, and every `"investigation.*"` key used in
  `app/api/investigations.py` (`investigation.create`, `investigation.list`,
  `investigation.get`, `investigation.add_entity`, `investigation.add_evidence`,
  `investigation.delete`).
- `general`: empty `frozenset()` — no tools.

Import the op-key constants from their owning modules in `profiles.py` rather than
retyping literals, so a future rename elsewhere breaks the import, not silently diverges.

- [ ] **Step 1: Write failing rule-table tests**

```python
# backend/tests/test_agent_router.py
import pytest
from app.security.agents.router import route

@pytest.mark.asyncio
async def test_shell_command_routes_to_shell_network():
    r = await route("curl -I https://example.com and show me the headers")
    assert r["agent"] == "shell_network"
    assert r["reason"] == "rule"

@pytest.mark.asyncio
async def test_nid_routes_to_people_identity():
    r = await route("look up 1200480002578150")
    assert r["agent"] == "people_identity"
    assert r["reason"] == "rule"

@pytest.mark.asyncio
async def test_route_query_routes_to_map_geo():
    r = await route("find a route from Kigali to Musanze")
    assert r["agent"] == "map_geo"
    assert r["reason"] == "rule"

@pytest.mark.asyncio
async def test_latest_news_routes_to_web_research():
    r = await route("what's the latest news on this company")
    assert r["agent"] == "web_research"
    assert r["reason"] == "rule"

@pytest.mark.asyncio
async def test_ambiguous_message_falls_back_to_model():
    async def fake_model_classify(message: str) -> str | None:
        return "shell_network"
    r = await route("check example.com", model_classify=fake_model_classify)
    assert r["agent"] == "shell_network"
    assert r["reason"] == "model"

@pytest.mark.asyncio
async def test_model_classify_failure_falls_back_to_general():
    async def failing_model_classify(message: str) -> str | None:
        raise RuntimeError("provider unreachable")
    r = await route("check example.com", model_classify=failing_model_classify)
    assert r["agent"] == "general"
    assert r["reason"] == "fallback"

@pytest.mark.asyncio
async def test_model_classify_unparsable_falls_back_to_general():
    async def junk_model_classify(message: str) -> str | None:
        return "not-a-real-agent-id"
    r = await route("check example.com", model_classify=junk_model_classify)
    assert r["agent"] == "general"
    assert r["reason"] == "fallback"

@pytest.mark.asyncio
async def test_forced_agent_wins_even_if_rules_disagree():
    r = await route("curl -I https://example.com", forced="web_research")
    assert r["agent"] == "web_research"
    assert r["reason"] == "manual"

@pytest.mark.asyncio
async def test_plain_chat_with_no_signals_routes_to_general():
    r = await route("thanks, that makes sense")
    assert r["agent"] == "general"
    assert r["reason"] in ("rule", "fallback")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_agent_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.security.agents'`

- [ ] **Step 3: Implement `profiles.py`**

Define `AgentProfile`, `PROFILES`, `AGENT_IDS`, and the six prompts, using the
`allowed_tools` sets specified above. Each `system_prompt` states the agent's scope in
one paragraph; `shell_network`'s prompt additionally states, verbatim in substance:
"Report only what the command's actual output shows. If a command fails, times out, or
returns nothing, say so explicitly — never infer or guess a result." `max_steps` is `8`
for `shell_network` and `investigations_files`, `5` for the others, `3` for `general`.

- [ ] **Step 4: Implement `router.py`**

`score_rules(message: str) -> dict[str, float]` scores each agent id (0.0–1.0) using
simple pattern checks: shell-token regex (`\b(curl|nmap|dig|whois|nc|ssh)\b` or a
leading `$`/shell-pipe shape) and URLs/domains for `shell_network`; `\b\d{16}\b` (NID) or
a phone-number-shaped token for `people_identity`; `\b(route|directions|navigate|map|
place|near me)\b` for `map_geo`; `\b(search|news|latest|find out|look up online)\b` for
`web_research`; `\b(investigation|evidence|save (this )?as|write (a )?(file|report))\b`
for `investigations_files`. `route()`:
1. If `forced` is given and is a key in `PROFILES`, return
   `{"agent": forced, "reason": "manual", "confidence": 1.0}`.
2. Compute `scores = score_rules(message)`. If the top score is `>= 0.6` and beats the
   runner-up by `>= 0.2`, return `{"agent": top, "reason": "rule", "confidence": top_score}`.
3. Otherwise call `model_classify(message)` (default implementation sends one short
   prompt asking the model to reply with exactly one agent id from `AGENT_IDS`, via the
   existing chat provider) inside a `try/except Exception`. If it raises, times out, or
   returns a string not in `AGENT_IDS`, return
   `{"agent": "general", "reason": "fallback", "confidence": 0.0}`.
4. If it returns a valid id, return `{"agent": id, "reason": "model", "confidence": 0.5}`.
5. If no rule reached the threshold and no model_classify was resolvable at all (e.g.
   message has zero signal and default classify also yields nothing), return
   `{"agent": "general", "reason": "rule", "confidence": top_score}` — so
   `test_plain_chat_with_no_signals_routes_to_general` passes via step 2's fallback,
   not step 3, when scores are all near zero but General still "wins" by being the
   `general` key's own weak rule match (treat unmatched text as a `general` rule hit at
   low confidence so the threshold-miss path in step 2 already resolves it without a
   model call).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_agent_router.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/security/agents tests/test_agent_router.py
git commit -m "feat(agents): add agent profiles and rule/model router

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Enforce agent toolset in `run_turn`

**Files:**
- Modify: `backend/app/security/orchestrator.py` (the `run_turn` function and
  `protocol_system_message`/catalogue-building call sites)
- Test: `backend/tests/test_chat_api.py` (new test functions) or a new
  `backend/tests/test_orchestrator_agents.py` if `test_chat_api.py`'s fixtures don't fit
  — prefer adding to whichever file already builds a `FakeOllama` + session fixture for
  `run_turn`.

**Interfaces:**
- Consumes: `AgentProfile` from Task 1 (`profiles.PROFILES`, `profiles.AGENT_IDS`).
- Produces: `run_turn(..., agent: "AgentProfile | None" = None)` — when `agent` is
  `None`, behavior is unchanged (today's full catalogue, for any direct caller that
  still omits it). When `agent` is given:
  - The system message built in `run_turn` additionally includes `agent.system_prompt`.
  - `max_steps` for the loop becomes `min(settings.tool_max_agent_steps, agent.max_steps)`.
  - Any proposed tool call whose `op_key` is not in `agent.allowed_tools` (and is not
    one of the always-allowed non-catalogue ops: file/install flows already special-cased
    in the existing code, which are unaffected) is rejected the same way an operator
    decline is handled today: yield `{"type": "tool_denied", "operation": op_key,
    "params": op_params}`, append the assistant's attempted call plus a user-role
    message to `convo` stating `"<op_key> is not available to the <agent.name> agent.
    Do not retry it; use only your assigned tools, or write your final answer."`, and
    `continue` the loop — mirroring the existing shell-auto-run-denied block's shape.

- [ ] **Step 1: Write failing tests**

```python
# in backend/tests/test_chat_api.py (or new file), reusing existing FakeOllama fixture
@pytest.mark.asyncio
async def test_run_turn_blocks_tool_outside_agent_allowlist(session, ...):
    from app.security.agents.profiles import PROFILES
    from app.security.orchestrator import run_turn
    provider = FakeOllama(replies=[
        json.dumps({"action": "tool", "operation": "shell.run",
                    "params": {"command": "id"}}),
        json.dumps({"action": "final", "answer": "done"}),
    ])
    events = [ev async for ev in run_turn(
        session, user_id=..., conversation_id=None,
        history=[AIMessage(role="user", content="search the web")],
        provider=provider, agent=PROFILES["web_research"],
    )]
    denied = [e for e in events if e["type"] == "tool_denied"]
    assert denied and denied[0]["operation"] == "shell.run"
    calls = [e for e in events if e["type"] == "tool_call"]
    assert not any(c["operation"] == "shell.run" for c in calls)

@pytest.mark.asyncio
async def test_run_turn_allows_tool_inside_agent_allowlist(session, ...):
    from app.security.agents.profiles import PROFILES
    from app.security.orchestrator import run_turn
    provider = FakeOllama(replies=[
        json.dumps({"action": "tool", "operation": "web.search",
                    "params": {"query": "example"}}),
        json.dumps({"action": "final", "answer": "done"}),
    ])
    events = [ev async for ev in run_turn(
        session, user_id=..., conversation_id=None,
        history=[AIMessage(role="user", content="search the web")],
        provider=provider, agent=PROFILES["web_research"],
    )]
    assert any(e["type"] == "tool_call" and e["operation"] == "web.search" for e in events)
```

Adapt fixture setup (`session`, `user_id`, capability stubs) to match whatever
`test_chat_api.py` or the nearest existing `run_turn`-driving test already sets up —
read that file's existing `run_turn`/service fixtures before writing these two tests so
`session`/auth/capabilities mocking matches established patterns exactly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_chat_api.py -k agent_allowlist -v`
Expected: FAIL — `run_turn() got an unexpected keyword argument 'agent'`

- [ ] **Step 3: Implement the `agent` parameter in `run_turn`**

Add `agent: "profiles.AgentProfile | None" = None` to `run_turn`'s signature (import
`profiles` from `app.security.agents`). After `sys_msg = await
protocol_system_message(max_steps)`, if `agent is not None` append
`AIMessage(role="system", content=agent.system_prompt)` to `convo` and recompute
`max_steps = min(max_steps, agent.max_steps)` before the `for step in
range(max_steps + 1)` loop. Inside the tool-call branch, immediately after computing
`op_key`/`op_params` and before the existing shell-auto-run check, insert the allowlist
check: if `agent is not None and op_key not in agent.allowed_tools`, yield
`tool_denied`, append the assistant/user messages described above, `continue`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_chat_api.py -k agent_allowlist -v`
Expected: PASS

- [ ] **Step 5: Run the full orchestrator/chat test suite for regressions**

Run: `cd backend && pytest tests/test_chat_api.py tests/test_agent_router.py -v`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/security/orchestrator.py tests/test_chat_api.py
git commit -m "feat(agents): enforce per-agent tool allowlist in run_turn

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Always-on routed multi-agent in `run_multi`, plus `agent_selected` events

**Files:**
- Modify: `backend/app/security/orchestrator.py` (`run_multi`, `_subtask_prompt` call
  sites)
- Test: `backend/tests/test_chat_api.py` or a new `backend/tests/test_orchestrator_agents.py`
  (same file chosen in Task 2)

**Interfaces:**
- Consumes: `route()` and `profiles.PROFILES` from Task 1; the `agent` param on
  `run_turn` from Task 2.
- Produces: `run_multi(..., agent: str | None = None)` — the new last parameter is a
  manual agent id (or `None` for auto). Behavior:
  - If `len(plan) < 2` (today's single-subtask shortcut): call `route(objective,
    forced=agent)`, yield `{"type": "agent_selected", "agent": result["agent"],
    "reason": result["reason"], "confidence": result["confidence"]}`, then call
    `run_turn(..., agent=PROFILES[result["agent"]])` and yield its events — replacing
    the current unrouted `run_turn` call in that branch.
  - For the multi-subtask loop: for each subtask `i`, call
    `route(st["task"], forced=agent)`, yield `{"type": "agent_selected",
    "agent": result["agent"], "reason": result["reason"], "confidence":
    result["confidence"], "subtask": i}` before running that subtask's `run_turn` call,
    and pass `agent=PROFILES[result["agent"]]` into that `run_turn` call.
  - `agent_selected` events are yielded exactly like the existing `tool_proposed`/`token`
    events — i.e. plain `yield {...}` inside the async generator, no new wrapper type.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_run_multi_single_subtask_emits_one_agent_selected(session, ...):
    from app.security.orchestrator import run_multi
    provider = FakeOllama(replies=[
        json.dumps([{"title": "Answer", "task": "search the web for X"}]),  # planner
        json.dumps({"action": "final", "answer": "done"}),  # the routed run_turn's only step
    ])
    events = [ev async for ev in run_multi(
        session, user_id=..., conversation_id=None,
        history=[AIMessage(role="user", content="search the web for X")],
        provider=provider,
    )]
    selected = [e for e in events if e["type"] == "agent_selected"]
    assert len(selected) == 1
    assert selected[0]["agent"] == "web_research"

@pytest.mark.asyncio
async def test_run_multi_forced_agent_overrides_routing_for_every_subtask(session, ...):
    from app.security.orchestrator import run_multi
    provider = FakeOllama(replies=[
        json.dumps([
            {"title": "A", "task": "run shell command id"},
            {"title": "B", "task": "search the web"},
        ]),
        json.dumps({"action": "final", "answer": "a done"}),
        json.dumps({"action": "final", "answer": "b done"}),
        "final synthesis text",
    ])
    events = [ev async for ev in run_multi(
        session, user_id=..., conversation_id=None,
        history=[AIMessage(role="user", content="do A then B")],
        provider=provider, agent="general",
    )]
    selected = [e for e in events if e["type"] == "agent_selected"]
    assert len(selected) == 2
    assert all(e["agent"] == "general" and e["reason"] == "manual" for e in selected)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_chat_api.py -k run_multi_agent -v`
Expected: FAIL — `run_multi() got an unexpected keyword argument 'agent'` or missing
`agent_selected` events

- [ ] **Step 3: Implement the changes in `run_multi`**

Add `agent: str | None = None` as the final parameter. Replace the single-subtask
shortcut's bare `run_turn` call and the loop's `run_turn` call as described in
Interfaces, importing `route` from `app.security.agents.router` and `PROFILES` from
`app.security.agents.profiles` at the top of `orchestrator.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_chat_api.py -k "run_multi_agent" -v`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite for regressions**

Run: `cd backend && pytest tests/ -v`
Expected: PASS, no regressions (existing `run_multi`/`run_turn` callers unaffected since
`agent` defaults to `None`/no override)

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/security/orchestrator.py tests/test_chat_api.py
git commit -m "feat(agents): route every run_multi subtask and emit agent_selected

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Wire chat API to always use routed multi-agent

**Files:**
- Modify: `backend/app/api/chat.py` (`NewMessage`, `_drive_turn`, `post_message`)
- Test: `backend/tests/test_chat_api.py`

**Interfaces:**
- Consumes: `run_multi(..., agent: str | None)` from Task 3.
- Produces: `NewMessage.agent: str | None = None` (new field, alongside the now-ignored
  `mode` field which stays verbatim for compatibility). `_drive_turn` gains
  `agent: str | None = None` parameter, always calls
  `driver = orchestrator.run_multi` (drop the `mode == "multi"` branch — `run_turn` is no
  longer called directly from chat.py), and forwards `agent=agent` into the `run_multi`
  call. `post_message` passes `agent=body.agent` into `_drive_turn`.

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_post_message_forwards_agent_field_and_emits_agent_selected(
    async_client, conv_id, monkeypatch,
):
    # Reuse this file's existing FakeOllama + monkeypatched get_chat_provider pattern.
    resp = await async_client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "search the web", "agent": "web_research"},
    )
    assert resp.status_code == 200
    body = resp.text  # or however this file already reads the SSE stream
    assert "agent_selected" in body
    assert "web_research" in body
```

Match this test's request/assertion style exactly to whatever pattern
`test_chat_api.py` already uses to post a message and read its SSE stream (e.g. an
existing `test_post_message_...` test) rather than inventing a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_chat_api.py -k forwards_agent -v`
Expected: FAIL — 422 (unknown field rejected is not expected since extra fields are
typically ignored by pydantic unless forbidden; actual failure mode is no
`agent_selected` in the response) or assertion failure on missing `agent_selected`

- [ ] **Step 3: Implement the field and wiring**

Add `agent: str | None = None` to `NewMessage`. In `_drive_turn`, add `agent: str | None
= None` to its signature; inside the `if use_tools:` block replace
`driver = orchestrator.run_multi if mode == "multi" else orchestrator.run_turn` with
`driver = orchestrator.run_multi`, and add `agent=agent` to the `driver(...)` call's
kwargs. Keep the `mode` parameter accepted (still read from `body.mode` where
`_drive_turn` is invoked) but stop branching on it. In `post_message`, add
`agent=body.agent` to the `_drive_turn(...)` call's kwargs.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_chat_api.py -k forwards_agent -v`
Expected: PASS

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && pytest tests/ -v`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/api/chat.py tests/test_chat_api.py
git commit -m "feat(agents): always route chat turns through run_multi

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Frontend — agent selector and badge

**Files:**
- Modify: `frontend/src/lib/chat.ts` (`streamMessage`)
- Modify: `frontend/src/components/chat/ActionDeck.tsx`
- Modify: `frontend/src/pages/Chat.tsx` (`LiveTurn`, `applyEvent`, the `ActionDeck` call
  site, the turn-rendering JSX)

**Interfaces:**
- Consumes: the `agent_selected` SSE event shape from Task 3:
  `{agent: string, reason: "rule"|"model"|"manual"|"fallback", confidence: number,
  subtask?: number}`.
- Produces:
  - `streamMessage(conversationId, content, useTools, onEvent, signal?, autoApprove?,
    think?, agent?: string)` — the `mode: "auto" | "multi"` parameter is removed from
    the public signature; the request body sends `{..., agent}` instead of `{..., mode}`
    (server still defaults `mode` fine since it's optional with a default).
  - `ActionDeck` props drop `multi: boolean` / `onMultiChange`; add
    `agent: string` (one of `"auto"` or the six ids) and `onAgentChange: (v: string) =>
    void`, rendered as a labeled select/segmented control replacing the old "Multi-agent"
    `Toggle`, with options `Auto, Shell & Network, Web Research, Map & Geo, People &
    Identity, Investigations & Files, General`.
  - `LiveTurn` gains `agentInfo: {agent: string; reason: string}[] | null` (indexed by
    subtask number, or a single-element array for non-multi turns).
  - `applyEvent` gains an `else if (e.event === "agent_selected")` branch that pushes
    `{agent: e.data.agent, reason: e.data.reason}` into `turn.agentInfo`.
  - `Chat.tsx` renders a small badge (agent display name + reason) above each turn's
    content (and per-subtask if `agentInfo.length > 1`), and a click handler that
    re-sends the same user message with `agent` forced to a chosen id (reuse the
    existing resend/retry code path if one exists in this file; otherwise call
    `streamMessage` again with the same content and an explicit `agent`).

- [ ] **Step 1: Update `streamMessage` in `chat.ts`**

Change the signature's last two params from `(think = false, mode: "auto" | "multi" =
"auto")` to `(think = false, agent?: string)`, and change the body's
`JSON.stringify({...})` to send `agent` instead of `mode`. Update the one call site in
`Chat.tsx` found by `grep -n "streamMessage(" frontend/src/pages/Chat.tsx` to pass the
new `agent` state instead of `multi ? "multi" : "auto"`.

- [ ] **Step 2: Replace the Multi-agent toggle in `ActionDeck.tsx`**

Remove the `multi`/`onMultiChange` props and the `<Toggle checked={p.multi} ... />`
block (the one using the `Network` icon, at the location found by
`grep -n "onMultiChange" frontend/src/components/chat/ActionDeck.tsx`). Add `agent:
string` and `onAgentChange: (v: string) => void` props and render a labeled
`<select>` (matching this file's existing styling conventions for other controls in the
same `Section`) with `value={p.agent}` and an `onChange` calling `p.onAgentChange`,
options: `auto` (label "Auto"), `shell_network` ("Shell & Network"), `web_research`
("Web Research"), `map_geo` ("Map & Geo"), `people_identity` ("People & Identity"),
`investigations_files` ("Investigations & Files"), `general` ("General").

- [ ] **Step 3: Update `Chat.tsx` state, `LiveTurn`, and `applyEvent`**

Replace `const [multi, setMulti] = useState(() => LS.getBool("kai.multi", false));` and
its `useEffect` with
`const [agent, setAgent] = useState(() => LS.getString("kai.agent", "auto"));` and
`useEffect(() => { LS.setString("kai.agent", agent); }, [agent]);` (add `getString`/
`setString` to whichever `LS` helper module this file imports if it doesn't already
have string helpers — check `grep -n "LS\." frontend/src/pages/Chat.tsx | head -5` for
the import source first). Add `agentInfo: {agent: string; reason: string}[] | null` to
the `LiveTurn` interface, initialized to `null` where other `LiveTurn` fields are
initialized. In `applyEvent`, add the `agent_selected` branch described above
(push, don't replace, since multi-subtask turns emit several). Update the
`streamMessage(...)` call site to pass `agent === "auto" ? undefined : agent` instead of
`multi ? "multi" : "auto"`. Update the `<ActionDeck .../>` call site to pass
`agent={agent} onAgentChange={setAgent}` instead of `multi={multi}
onMultiChange={setMulti}`.

- [ ] **Step 4: Render the agent badge**

In the turn-rendering JSX (near where `turn.tools`/`turn.findings` are rendered per
turn), add a small badge element reading `turn.agentInfo` — for each entry render e.g.
`"{displayName(agent)} · {reason}"` using a `displayName` lookup map matching the labels
in Step 2, placed above the turn's content. Wire a click handler that calls
`streamMessage` again with the same last user content and the clicked badge's agent id
forced (follow this file's existing pattern for re-sending/retrying a turn if one
exists — check `grep -n "resend\|retry" frontend/src/pages/Chat.tsx` first; if none
exists, add a minimal one scoped to this feature: re-run the same `sendMessage`-equivalent
function this file already uses for the send button, with the target agent substituted
for the current `agent` state value for that one call only).

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/lib/chat.ts src/components/chat/ActionDeck.tsx src/pages/Chat.tsx
git commit -m "feat(agents): add agent selector and badge to chat UI

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end verification

**Files:** none created/modified — verification only.

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && pytest tests/ -v`
Expected: PASS, all tests including Tasks 1–4's new tests

- [ ] **Step 2: Run the frontend typecheck and build**

Run: `cd frontend && npm run build`
Expected: builds cleanly (this also runs `tsc --noEmit` per the existing `build` script)

- [ ] **Step 3: Manual smoke test**

Start the backend and frontend per `README.md`. In the chat UI: (a) send a shell-flavored
message ("curl -I https://example.com") with Agent set to Auto and confirm the badge
shows "Shell & Network · rule"; (b) send a message with Agent forced to "General" and
confirm the badge shows "General · manual" even though the content looks like a shell
task; (c) send a two-part message ("look up this NID, then search the web for recent
news about them") and confirm two agent badges appear, one per subtask.

- [ ] **Step 4: Commit any fixup changes found during smoke test, or note none needed**

```bash
git add -A
git commit -m "chore(agents): fixups from end-to-end smoke test

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
(Skip this commit if the smoke test found nothing to fix.)
