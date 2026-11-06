# Person investigation agents — design

Date: 2026-11-04 · Status: awaiting review

## Goal
One person search that checks the saved database (NID-seeded + scraped records) **and** the internet, always shows the person with everything known about them, finds every connection (kin and associates), lets the operator click any related person to open their card, and produces an evidence-grounded description of who they are and what they do. Task-specific agents are started only when the request needs them.

## Non-goals
- No new external data sources or paid APIs.
- No recursive/transitive graph expansion (one hop per click).
- No invented data: absent facts are reported as "not found".
- Not a Claude Code `.claude/agents` setup (decided: runs inside KAI).

## Existing code reused
`enrich/lookup.py` (`resolve_identity`), `enrich/people_search.py` (`search_people`), `enrich/family.py` (parents/siblings/children/extended), `discovery/*` (web search, dossier), `ai/ollama.py` (local `kai-security`), `database/repositories/audit_repo.py`, SSE helpers in `api/chat.py`.

## Architecture
New package `backend/app/agents/`:

| File | Purpose |
|---|---|
| `base.py` | `Agent` protocol: `name`, `can_handle(req) -> bool`, `async run(ctx) -> AgentResult`; `Fact`, `AgentResult`, `Ctx` |
| `router.py` | Deterministic rules choose agents; independent agents run in parallel (`asyncio.gather`, per-agent timeout); emits progress events |
| `db_agent.py` | Wraps `resolve_identity`/`search_people`: full person card (phones, parcels, photo, family) |
| `web_agent.py` | Wraps `discovery` search/dossier for the person's name + location; every hit keeps URL + timestamp |
| `relations_agent.py` | Kin + associates + shared-facts engine (below) |
| `analyst_agent.py` | Applies the analysis skill to the merged evidence bundle |
| `skills/people_analysis.md` | The professional analysis skill (versioned prompt + rules) |
| `grounding.py` | Post-generation check: drops analysis sentences not traceable to a fact |

Routing rules (no LLM in routing, so the local model's lack of tool-calling does not matter):
- Any identifier (NID / phone / name / image) → `db_agent`.
- Internet search requested, or DB found nothing → `web_agent`.
- Always after the person is resolved → `relations_agent`.
- "describe / analyse / who is / what does he do" → `analyst_agent` (runs last).

## Evidence model
Every fact: `{claim, value, source: db|web|inference, source_ref (record id or URL), retrieved_at, confidence}`. Inferences are labelled as such and never shown as confirmed. The person card is returned even if every other agent fails or returns nothing.

## relations_agent
**Kin** (reuses `family.py`): parents, children, siblings, extended family, and **spouse/partner**, inferred when a child's `father_names` and `mother_names` resolve to the subject plus one other person (the child is cited as evidence). A web-found spouse name is added as a separate, URL-sourced fact. `marital_status` is shown but does not by itself prove a spouse.

**Associates** (new): coworkers / same organisation (web evidence only — the NID data has no employer), same village/cell/address, shared phone, co-owned parcels (UPI), co-appearance on the same web page/photo/article, any other shared fact.

**Shared-facts engine:** compares the subject's fact set with every other person's. Output edge:
`{person_a, person_b, relation, shared: [{what, value, source}], confidence}` and always states *exactly what is shared* (e.g. "both at Acme Ltd — web: <url>"). Each shared value is weighted by rarity across the dataset (IDF-style): a phone, parcel or rare organisation scores high; a province or common name scores low. Edges below the threshold are hidden unless the UI "show weak links" toggle is on.

**Nodes:** in-system people carry a `nid`; web-only people carry name + source and are marked "not in the system" with a "look up in system" action.

## Click-through navigation
`GET /people/{nid}/investigate` returns that person's card + their one-hop relations. Clicking any related person calls it for that person. The UI keeps a breadcrumb trail and caches fetched cards for the session. Nothing is expanded beyond the clicked person.

## Analysis skill (`people_analysis.md`)
- Describe only what the evidence bundle supports; tag every statement with its fact ids / sources.
- Fixed sections: Identity, Location, Family & associates, Occupation & activity, Online presence, Confidence & gaps.
- Say "not found" rather than guess. Flag likely name collisions (web hits that may be a different person).
- Distinguish confirmed (db) from reported (web) from inferred.
- `grounding.py` verifies the generated text against the bundle and removes untraceable sentences.

## API
- `POST /people/investigate` — body: `{nid?, phone?, name?, image?, web: bool, analyse: bool}`; streams agent progress via SSE; final payload `{person, relations, web_findings, analysis, notes}`.
- `GET /people/{nid}/investigate` — one-hop card for click-through.
- KAI chat orchestrator can call the same entry point.
- Frontend: Relations panel (kin / associates, shared-thing chips with sources, weak-links toggle), Analysis tab with source chips, breadcrumb navigation.

## Safety, errors, limits
- Every investigation is written to the audit log (operator, query, agents run).
- Agent failure/timeout degrades only its section and is reported in `notes`; never fails the whole request.
- Existing rate limiter and SSRF-guarded fetchers are reused for web access.
- Associate and kin links are inferences; the UI always shows the evidence behind them. Existing disclaimer wording is kept.

## Testing
- Unit: router rules; spouse inference (shared children, one parent only, same-name collisions, implausible ages); rarity weighting and threshold; grounding check drops untraceable sentences.
- Integration: seeded DB + mocked web agent → person, spouse card, associates, analysis; click-through returns one hop only; agent timeout degrades gracefully; audit entry written.

## Open items for the plan
- Exact rarity threshold default (start conservative, tune on seeded data).
- Where `orgs`/`titles` live for web-only people (face-index `extra` today) and whether `web_agent` should persist its findings.
