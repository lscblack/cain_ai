# Person Investigation Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One person investigation that searches the saved DB and the web, finds every kin/associate connection with the exact shared facts, supports click-through to related people, and produces an evidence-grounded description.

**Architecture:** New `backend/app/agents/` package: small async agents (`db`, `web`, `relations`, `analyst`) selected by a deterministic router and run in parallel; every fact is a provenance-carrying `Fact`; analysis text is post-checked so every sentence cites an existing fact. Exposed via SSE endpoints and a React Relations/Analysis UI.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, PostgreSQL, pytest-asyncio (`tests/conftest.py` fixtures `db_session`, `client`), Ollama `OllamaProvider.chat`, React + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-11-04-person-investigation-agents-design.md`

## Global Constraints
- Local-first, no new external services or paid APIs; web access reuses `app/discovery/*` (SSRF-guarded).
- Never invent data: absent facts are reported "not found"; inferences carry `source="inference"` and are never shown as confirmed.
- Every investigation writes an audit entry via `AuditRepository.record(action, actor_id=, detail=)`.
- One hop per click-through; no recursive graph expansion.
- Agent failure/timeout degrades only its section (reported in `notes`), never the whole request. Per-agent timeout: 25 s.
- Weak-link default threshold: `MIN_EDGE_CONFIDENCE = 50`.
- Spouse/partner is inferred only from shared children (child's `father_names`+`mother_names` resolve to subject + one other); `marital_status` alone never creates a partner.
- Keep README disclaimer wording: links are inferred, not confirmed.

## Review Focus
1. Subject is MARRIED but has no children in the DB → no partner invented; only `marital_status` shown.
2. Very common name matches many people → partner/relative marked ambiguous, not auto-linked.
3. Web search offline/erroring → person card still returned, `notes` explains.
4. Click-through on a web-only node (no NID) → returns the web-only card, not 404/500.
5. Same person is both sibling and coworker, or partner resolves to the subject → merged/deduped, never self-linked.
6. Model returns text with no valid citations → all sentences dropped, safe "no grounded analysis" message returned.

## File Structure
| File | Responsibility |
|---|---|
| `backend/app/agents/__init__.py` | package marker |
| `backend/app/agents/base.py` | `Fact`, `Request`, `AgentResult`, `Ctx`, `Agent` protocol |
| `backend/app/agents/partners.py` | partner inference from shared children |
| `backend/app/agents/shared_facts.py` | rarity weighting + shared-fact edge engine |
| `backend/app/agents/web_text.py` | pure `extract_spouse_names(text)` |
| `backend/app/agents/db_agent.py` | DB person card |
| `backend/app/agents/web_agent.py` | web/corpus findings → facts |
| `backend/app/agents/relations_agent.py` | kin + associates + edges |
| `backend/app/agents/grounding.py` | citation check |
| `backend/app/agents/skills/people_analysis.md` | the analysis skill |
| `backend/app/agents/analyst_agent.py` | build bundle, call model, ground |
| `backend/app/agents/router.py` | `select_agents`, `run_investigation` |
| `backend/app/api/investigate.py` | endpoints (SSE) |
| `backend/tests/test_agents_*.py` | tests per task |
| `frontend/src/lib/enrich.ts` (modify), `frontend/src/components/RelationsPanel.tsx`, `AnalysisTab.tsx` | UI |

---

### Task 1: Core types
**Files:** Create `backend/app/agents/__init__.py`, `base.py`; Test `backend/tests/test_agents_base.py`

**Interfaces — Produces:**
```python
@dataclass(frozen=True)
class Fact: id: str; claim: str; value: str; source: Literal["db","web","inference"]; source_ref: str; retrieved_at: str; confidence: int  # 0-100
@dataclass
class Request: nid: str|None=None; phone: str|None=None; name: str|None=None; image: bytes|None=None; web: bool=False; analyse: bool=False
@dataclass
class AgentResult: agent: str; ok: bool; facts: list[Fact]; data: dict; error: str|None=None
@dataclass
class Ctx: session: AsyncSession; user_id: uuid.UUID; request: Request; person: Person|None; results: dict[str, AgentResult]; emit: Callable[[str, dict], Awaitable[None]]
class Agent(Protocol): name: str; def can_handle(self, ctx: Ctx) -> bool; async def run(self, ctx: Ctx) -> AgentResult
def new_fact_id(n: int) -> str  # "F1","F2",...
```
- [ ] **Step 1:** Write `test_fact_is_frozen_and_confidence_bounded` (assert `Fact(..., confidence=101)` raises `ValueError` via `__post_init__`; mutating a Fact raises `FrozenInstanceError`) and `test_new_fact_id` (`new_fact_id(3) == "F3"`).
- [ ] **Step 2:** Run `cd backend && pytest tests/test_agents_base.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement `base.py` as above.
- [ ] **Step 4:** Run the same → PASS.
- [ ] **Step 5:** Commit `feat(agents): core fact/agent types`.

### Task 2: Partner inference
**Files:** Create `backend/app/agents/partners.py`; Test `backend/tests/test_agents_partners.py`

**Interfaces — Consumes:** `family.children_of(session, parent) -> list[tuple[Person,str]]`, `family._people_named(session, name) -> list[Person]`, `family.person_name`, `family.same_name`. **Produces:**
```python
@dataclass
class PartnerLink: partner: Person|None; partner_name: str; children_nids: list[str]; confidence: int; ambiguous: bool
async def infer_partners(session: AsyncSession, person: Person) -> list[PartnerLink]
```
- [ ] **Step 1:** Tests (use `db_session`, `Person(nid=..., raw={}, ...)` as in `tests/test_family.py`): 
  - `test_partner_from_two_shared_children`: subject JEAN NZEYIMANA (M), partner MARIE UWASE (F) in DB, two children naming both → one link, `partner.nid` == partner's, `children_nids` has 2, `confidence >= 70`, `ambiguous False`.
  - `test_one_child_lower_confidence_than_two` (one child confidence < two-child confidence).
  - `test_no_children_no_partner` (subject `marital_status="MARRIED"`, no children → `[]`) — Review Focus 1.
  - `test_ambiguous_common_name`: two people named MARIE UWASE exist → `partner is None`, `ambiguous True`, `confidence <= 40` — Review Focus 2.
  - `test_partner_never_subject`: child lists subject as both parents' name → no self link — Review Focus 5.
  - `test_partner_name_not_in_db`: partner_name returned, `partner None`, `ambiguous False`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. For each child from `children_of`, take the other parent's recorded name (`mother_names` if subject was "father", else `father_names`), group by normalised token set, resolve via `_people_named`. Confidence = `min(90, 60 + 10*(n_children-1))` when exactly one DB candidate; 40 and `ambiguous=True` when >1; 40 when none in DB.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(agents): infer partners from shared children`.

### Task 3: Shared-facts engine
**Files:** Create `backend/app/agents/shared_facts.py`; Test `backend/tests/test_agents_shared_facts.py`

**Interfaces — Consumes:** `Person`, `PhoneNumber`, `ParcelOwnership` (`app/database/models/enrich.py`). **Produces:**
```python
MIN_EDGE_CONFIDENCE = 50
@dataclass
class SharedFact: what: str; value: str; source: str; source_ref: str; count: int; total: int   # count = how many people hold this value
@dataclass
class Edge: person_a: str; person_b: str|None; name_b: str; relation: str; shared: list[SharedFact]; confidence: int
def rarity_score(count: int, total: int) -> int            # 0-100; 100 = unique, ~0 = ubiquitous
def edge_confidence(shared: list[SharedFact]) -> int       # max rarity, +5 per extra independent shared fact, cap 95
async def find_db_edges(session: AsyncSession, person: Person) -> list[Edge]   # shared phone, co-owned parcel (UPI), same district+cell+village
def merge_edges(edges: list[Edge]) -> list[Edge]           # one edge per (person_b/name_b), shared lists unioned, never self (person_a==person_b)
```
- [ ] **Step 1:** Tests: `test_rarity_unique_high_common_low` (`rarity_score(2, 10000) >= 50`; `rarity_score(3000, 10000) < 50`); `test_shared_phone_edge` (two persons with same `PhoneNumber.msisdn` → edge relation `"shared phone"`, confidence ≥ 50); `test_co_owned_parcel_edge`; `test_same_village_edge_is_weak_when_village_large` (30 people in same village → edge confidence < `MIN_EDGE_CONFIDENCE`); `test_merge_edges_unions_and_drops_self` (sibling+coworker same person → one edge, two shared facts; self edge removed) — Review Focus 5.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement with SQL `COUNT` queries for `count`/`total`. `rarity_score = round(100 * log(total/count) / log(total))` clamped 0–100 (total ≤ 1 → 0).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(agents): rarity-weighted shared-facts engine`.

### Task 4: Web text extraction
**Files:** Create `backend/app/agents/web_text.py`; Test `backend/tests/test_agents_web_text.py`

**Produces:** `def extract_spouse_names(text: str) -> list[str]` — pure; matches "wife of X", "husband of X", "married to X", "spouse X", returns capitalised name strings (≥2 tokens), deduped, order kept.
- [ ] **Step 1:** Tests: `"She is the wife of Jean Paul Nzeyimana."` → `["Jean Paul Nzeyimana"]`; `"married to Marie Uwase and living in Kigali"` → `["Marie Uwase"]`; `"no family mentioned"` → `[]`; single-token `"wife of John"` → `[]`.
- [ ] **Step 2–4:** Fail → implement with a compiled regex → pass.
- [ ] **Step 5:** Commit `feat(agents): extract spouse names from web text`.

### Task 5: db_agent and web_agent
**Files:** Create `db_agent.py`, `web_agent.py`; Test `backend/tests/test_agents_db_web.py`

**Interfaces — Consumes:** `enrich.lookup.resolve_identity(session, user_id, *, nid, phone, name) -> dict`, `discovery.dossier.gather_dossier(session, term, *, as_name=True) -> dict`, `discovery.search.search_candidates_free(queries, ...) -> dict[str,str]`, `discovery.search.search_available() -> bool`. **Produces:** `class DbAgent` (`name="db"`; `can_handle`: any of nid/phone/name/image set; `run` → `AgentResult.data={"people": [...cards], "person_nid": str|None}` and one `source="db"` Fact per populated card field, `source_ref=f"person:{nid}"`; sets `ctx.person` to the top-ranked `Person` row) and `class WebAgent` (`name="web"`; `can_handle`: `request.web` or DB found nothing; `run` → facts with `source="web"`, `source_ref=<url>`, confidence ≤ 40 for name-only matches; `data={"findings": [...], "spouse_names": [...]}` using `extract_spouse_names` on dossier page text).
- [ ] **Step 1:** Tests: `test_db_agent_returns_card_and_sets_person` (seed Person, run with `nid`, assert `ctx.person.nid` and a Fact with claim `"national id"`); `test_db_agent_not_found_is_ok_with_empty_people`; `test_web_agent_offline_degrades` (monkeypatch `search_candidates_free` to raise → `ok False`, `error` set, no exception; Review Focus 3); `test_web_agent_facts_carry_url` (monkeypatch dossier + search; every Fact has `source=="web"` and a URL `source_ref`).
- [ ] **Step 2–4:** Fail → implement → pass.
- [ ] **Step 5:** Commit `feat(agents): db and web agents`.

### Task 6: relations_agent
**Files:** Create `relations_agent.py`; Test `backend/tests/test_agents_relations.py`

**Interfaces — Consumes:** Tasks 2, 3, 5; `family.find_relatives`, `family.extended_family`, `family.relatives_out`, `family.extended_out`. **Produces:** `class RelationsAgent` (`name="relations"`; `can_handle`: `ctx.person is not None`; `run` → `data={"kin": {"partners": [...], "parents": [...], "children": [...], "siblings": [...], "extended": [...]}, "associates": [Edge-dicts], "nodes": [{"nid": str|None, "name": str, "in_system": bool, "source_ref": str|None}]}`; partner `Fact`s use `source="inference"`; web spouse names (from `ctx.results["web"].data["spouse_names"]`) are separate `source="web"` Facts and are looked up via `family._people_named` — in-system match becomes a node with `nid`, otherwise `in_system False`; edges below `MIN_EDGE_CONFIDENCE` go under `data["weak_associates"]`; web org matches (same org string in `ctx.results["web"]` facts claim `"organisation"` and another in-system person's indexed `orgs`) produce a `coworker` edge, `source="web"`, confidence ≤ 60).
- [ ] **Step 1:** Tests: `test_kin_and_partner_present`; `test_weak_links_separated`; `test_web_spouse_in_system_becomes_clickable_node`; `test_web_only_spouse_is_marked_not_in_system`; `test_coworker_edge_is_web_sourced_unconfirmed`; `test_married_without_children_has_no_partner` (Review Focus 1, at agent level).
- [ ] **Step 2–4:** Fail → implement → pass.
- [ ] **Step 5:** Commit `feat(agents): relations agent (kin + associates)`.

### Task 7: Analysis skill, grounding, analyst_agent
**Files:** Create `skills/people_analysis.md`, `grounding.py`, `analyst_agent.py`; Test `backend/tests/test_agents_analyst.py`

**Interfaces — Produces:**
```python
def build_bundle(facts: list[Fact]) -> str            # lines: "[F3] claim: value (source=db, ref=person:123, conf=90)"
def ground(text: str, facts: list[Fact]) -> tuple[str, list[str]]   # (kept text, dropped sentences); a sentence is kept only if it contains >=1 "[F#]" and every cited id exists in facts; section headings and the "Confidence & gaps" section are exempt
def load_skill() -> str                               # reads skills/people_analysis.md
class AnalystAgent: name="analyst"; can_handle: ctx.request.analyse; run -> data={"analysis": str, "dropped": list[str]}; uses OllamaProvider.chat([system=skill, user=bundle]); if provider unavailable -> ok False with error
```
Skill file must contain, verbatim, the rules: describe only what the bundle supports; cite `[F#]` on every statement; sections **Identity, Location, Family & associates, Occupation & activity, Online presence, Confidence & gaps**; write "not found" instead of guessing; flag possible name collisions; distinguish confirmed (db) / reported (web) / inferred.
- [ ] **Step 1:** Tests: `test_ground_keeps_cited_drops_uncited`; `test_ground_drops_unknown_fact_id` (`[F99]`); `test_ground_exempts_gaps_section`; `test_all_uncited_returns_safe_message` (analyst with a fake provider returning uncited text → `analysis == "No grounded analysis could be produced from the available evidence."`; Review Focus 6); `test_skill_file_has_required_sections` (each of the six headings appears in `load_skill()`); `test_build_bundle_format`.
- [ ] **Step 2–4:** Fail → implement → pass.
- [ ] **Step 5:** Commit `feat(agents): people-analysis skill, grounding and analyst agent`.

### Task 8: Router
**Files:** Create `router.py`; Test `backend/tests/test_agents_router.py`

**Interfaces — Produces:**
```python
def select_agents(req: Request, person_found: bool) -> list[str]   # rules from the spec
async def run_investigation(session, user_id, req: Request, emit) -> dict
# -> {"person": dict|None, "relations": dict|None, "web_findings": list, "analysis": str|None, "facts": [Fact dicts], "notes": [str]}
```
Order: `db` (and `web` in parallel when selected) → `relations` → `analyst`. Each run wrapped in `asyncio.wait_for(..., 25)`; exceptions/timeouts become `AgentResult(ok=False, error=...)` and a `notes` entry. Emits `("agent_start"|"agent_done"|"agent_error", {"agent": name})`. Fact ids are assigned sequentially across all results before the analyst runs. Writes audit via `AuditRepository(session).record("people.investigate", actor_id=user_id, detail={"query": {...no image bytes...}, "agents": [...]})`.
- [ ] **Step 1:** Tests: `test_select_nid_only` (`["db","relations"]`); `test_select_web_and_analyse` (includes `web` and `analyst`, analyst last); `test_select_nothing_found_adds_web`; `test_agent_timeout_degrades` (fake agent sleeps past a patched timeout → result still returned, note present); `test_audit_written` (AuditLog row with action `people.investigate`); `test_person_returned_when_web_fails` (Review Focus 3).
- [ ] **Step 2–4:** Fail → implement → pass.
- [ ] **Step 5:** Commit `feat(agents): deterministic router and investigation runner`.

### Task 9: API endpoints
**Files:** Create `backend/app/api/investigate.py`; Modify `backend/app/main.py` (add `from app.api import investigate` and `app.include_router(investigate.router)` after `enrich.router`); Test `backend/tests/test_investigate_api.py`

**Interfaces — Produces:** same router prefix as `api/enrich.py`:
- `POST /people/investigate` — JSON body `{nid?, phone?, name?, web: bool=false, analyse: bool=false}`; `StreamingResponse` SSE using the `_sse(event, data)` format from `api/chat.py` (copy-free: import it); events `agent_start/agent_done/agent_error` then `result`. Requires `get_current_operator`.
- `GET /people/{nid}/investigate` — non-streaming one-hop card (`person` + `relations`), 404 only when neither DB nor web-only node exists; for a `web:`-prefixed id returns the web-only card (Review Focus 4).
- [ ] **Step 1:** Tests via `client`: `test_requires_auth` (401); `test_investigate_streams_result_event`; `test_click_through_returns_one_hop` (related person's relations contain no `extended` of extended); `test_web_only_node_returns_card_not_404`; `test_empty_request_400`.
- [ ] **Step 2–4:** Fail → implement → pass. Run the full suite: `cd backend && pytest -q` → all PASS.
- [ ] **Step 5:** Commit `feat(api): person investigation endpoints`.

### Task 10: Chat hook
**Files:** Modify `backend/app/security/orchestrator.py` (add an operation `people.investigate` calling `run_investigation`), Test `backend/tests/test_orchestrator.py` (extend)
- [ ] **Step 1:** Add `test_orchestrator_can_call_people_investigate` following the file's existing fake-provider pattern; assert the tool result contains `person` and is audited.
- [ ] **Step 2–4:** Fail → register the operation using the file's existing op-registration pattern → pass.
- [ ] **Step 5:** Commit `feat(chat): expose people investigation to KAI chat`.

### Task 11: Frontend
**Files:** Modify `frontend/src/lib/enrich.ts` (types `Fact`, `Edge`, `InvestigateResult`; `enrichApi.investigate(body, onEvent)` using the SSE helper pattern in `lib/api`; `enrichApi.personCard(nid)`); Create `frontend/src/components/RelationsPanel.tsx`, `AnalysisTab.tsx`; Modify the page rendering people-search results (locate with `grep -rn "people/search" frontend/src`).
- RelationsPanel: groups Kin / Associates; each edge shows shared-thing chips (`what: value` + source link); "Show weak links" toggle (default off, uses `weak_associates`); each related person is a button calling `personCard`; web-only nodes show a "not in system" badge and a "look up in system" action; breadcrumb trail with back navigation; session cache keyed by nid.
- AnalysisTab: renders analysis text with `[F#]` converted to chips linking to the fact's source; shows `dropped` count and `notes`.
- [ ] **Step 1:** Implement types and API calls; run `cd frontend && pnpm tsc --noEmit` → no errors.
- [ ] **Step 2:** Implement the two components and wire them into the people-search page.
- [ ] **Step 3:** Run `cd frontend && pnpm build` → success.
- [ ] **Step 4:** Manual check using `run` skill: search a seeded NID, confirm person card always shows, relations appear, clicking a relative opens their card and breadcrumb returns; weak-links toggle works.
- [ ] **Step 5:** Commit `feat(web): relations panel, analysis tab and click-through`.

---

## Self-review
- **Spec coverage:** agents/router (T1,5,6,7,8); evidence model (T1); partner inference (T2); shared-facts + rarity + threshold + dedupe (T3); web spouse + web-only nodes (T4,6); coworkers web-only (T6); analysis skill + grounding (T7); endpoints, one-hop click-through (T9); audit + degradation + timeouts (T8); chat integration (T10); UI incl. weak toggle/breadcrumb/cache (T11).
- **Open spec items decided:** threshold = 50 (constraint above); web-only `orgs`/`titles` are read from `gather_dossier` output and the face-index `extra`, `web_agent` does not persist findings (YAGNI).
- **Type consistency:** `Fact`, `Request`, `AgentResult`, `Ctx`, `Edge`, `SharedFact`, `PartnerLink` names are identical across tasks.
