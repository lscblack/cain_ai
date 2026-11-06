# KAI Agent Routing — Design

Sub-project 1 of 4. Later sub-projects (separate specs) reuse the agents defined here:
2. Web search UX (clickable results, open public pages, summarize, view more)
3. Map in chat (satellite and other modes, full screen, KAI actions: places, routes)
4. Mobile KAI chat (Flutter, `mobile/`)

## Problem

KAI's model picks tools itself from a single generic catalogue. On shell/`curl`/network
analysis it can choose the wrong tool, look in the wrong place, report things the output
does not show, and burn tokens and time (the model is local and often CPU-only).

## Goals

- Classify each task and route it to a specialist agent with a narrow toolset.
- Show the operator which agent was chosen and why; let them override it.
- Multi-agent decomposition is always on, with no toggle.
- Shell/network agent reports only what command output shows.

## Non-goals

Clickable web results, map features and the mobile chat (sub-projects 2–4).

## Decisions

- **Classification:** rules first (zero tokens); one short model call only when rules are
  unsure; General is the final fallback. A manual pick skips classification.
- **Roster (v1):** Shell & Network, Web Research, Map & Geo, People & Identity,
  Investigations & Files, General.
- **Approach:** router in front of `run_turn`; an agent is a profile that restricts the
  tools the model is offered and allowed to call.

## Backend

New package `backend/app/security/agents/`:

- `profiles.py` — six profiles. Each has `id`, display name, system prompt,
  `allowed_tools` (operation keys from `security/registry.py` plus web, map,
  investigation and people ops), and `max_steps`.
- `router.py` — `route(message, history, forced=None)` returns
  `{agent, reason: "rule"|"model"|"manual"|"fallback", confidence}`. The rule table is
  plain data. Signals include `curl`/`nmap`/`dig`/shell syntax, URLs, 16-digit NIDs,
  phone numbers, place/route words, and "search/news/latest".
  If one agent clearly wins, use it. If scores are close or all low, make one short
  model call to label the task. If that fails or is unclear, use General.
- `run_turn` (`security/orchestrator.py`) accepts an `agent` argument. It builds the tool
  catalogue from `allowed_tools` and rejects any other operation with a
  "not available to this agent" result, even if the model requests it.
- `run_multi` becomes the default path in `api/chat.py`. The planner splits the objective
  into subtasks. A one-subtask plan runs as a normal single-agent turn. Each subtask is
  routed with `route()` and run as a sub-agent with that agent's tools.
- The `mode` field stays in the request model for compatibility and is ignored. A new
  optional `agent` field carries a manual choice.
- New SSE event `agent_selected` with `{agent, reason, confidence, subtask?}`.
- Shell & Network prompt: report only what the command output shows; if a command fails
  or returns nothing, say so; do not infer results.

## Frontend

- `ActionDeck.tsx`: replace the Multi-agent toggle with an Agent selector
  (Auto by default, plus the six agents). Persist in localStorage like other toggles.
- `Chat.tsx`: handle `agent_selected`; show an agent badge with the reason on each turn
  or subtask. Clicking the badge re-runs that turn with another agent.

## Errors

- Classifier or model failure falls back to General and the badge says so.
- A tool call outside the agent's set returns "not available to this agent" to the model;
  the UI offers to switch agent.

## Testing

- Table-driven tests for the rule router: sample messages per agent (`curl -I example.com`,
  a NID, "route from A to B", "latest news on X") and ambiguous cases that reach the model
  fallback.
- `run_turn` blocks tools outside `allowed_tools`.
- A multi-part message produces routed subtasks.
- Frontend: the selector and badge render.
