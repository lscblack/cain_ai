# KAI Capabilities Surfacing + Script Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the full tool catalogue in the chat Capability Palette (with one-click apt install) and add a Run button that executes a generated `.sh` asset in KAI's live terminal, elevating to root via the desktop password popup.

**Architecture:** Backend reuses the existing shell executor in `security/service.py`: the post-validation execution body is factored into a shared helper so both `shell.run` and a new workspace-script runner share one tested path (non-root → persistent `exec_in_session`; root → one-shot `pkexec bash -lc …`). A thin validated `/tools/run-script` endpoint calls it. Frontend reads the inventory it already fetches to render installable tools, and adds a Run button to `.sh` file chips.

**Tech Stack:** FastAPI + async SQLAlchemy (Python), pytest; React + TypeScript + Vite (pnpm), lucide-react.

**Spec:** docs/superpowers/specs/2026-11-08-capabilities-and-script-run-design.md

## Global Constraints

- One-click install is **apt only**; go/pip/github/gem/kali tools are shown for awareness, never one-click installed (backend `_apt_only` enforces this).
- Script execution is a **shell execution**: it obeys `caps.shell_enabled` and (for root) `caps.shell_sudo`, exactly like `shell.run`. No new privilege path.
- Root runs one-shot via the existing `run_shell(..., sudo=True)` → `pkexec` (desktop password popup). Never build a shell string from model input; the script name is validated and run as `bash ./<safe-relative-name>`.
- Scripts run only from inside the operator's own workspace (`workspace.operator_dir(user_id)`); no path traversal, name must end in `.sh`.
- Do not commit `.env` or secrets. Attribution trailer on commits: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- No regressions to agent routing, the install workflow, or existing shell tests.

## Review Focus

- A script name with spaces or shell metacharacters (`a b.sh`, `x;rm.sh`) must stay contained by `_safe_relname` + the relative `./` prefix — Task 1 tests both.
- A `sudo` script run while `caps.shell_sudo` is off must be blocked with `sudo_disabled`, not executed unprivileged silently — Task 1 test.
- A long/interactive script returns `running: true` and must not wedge the shared `exec_in_session` for the next `shell.run` — Task 1 asserts `running` surfaces; session semantics are unchanged by reuse.
- Installing a tool from the palette must refresh inventory so the just-installed tool becomes runnable without a full reload — Task 5 test.
- The orchestrator's "never write `missing_tools.txt`, install instead" rule must remain in the assembled system prompt — Task 3 regression test.

---

## Task 1: Shared shell executor + `run_workspace_script`

**Files:**
- Modify: `backend/app/security/service.py` (refactor `_run_shell_op` ~lines 258–373; add shared helper + `run_workspace_script`)
- Test: `backend/tests/test_run_script.py` (create)

**Interfaces:**
- Consumes: `ws.operator_dir`, `ws.session_cwd`, `ws._safe_relname`, `ws.list_files` (workspace); `terminal.exec_in_session`; `run_shell`; `ExecResult`, `redact`, `_record`, `get_settings`; `SHELL_OP_KEY`.
- Produces:
  - `async def _exec_shell_command(session, *, user_id: uuid.UUID, conversation_id: uuid.UUID | None, command: str, sudo: bool, interactive: bool, caps, extra_args: dict | None = None) -> dict` — the current execution body (rate-limit check onward: pkexec-vs-session branch, `_record`, `AuditLog`, new-files registration, `out` assembly including `running`). Returns the same dict `_run_shell_op` returns today.
  - `async def run_workspace_script(session, *, user_id: uuid.UUID, conversation_id: uuid.UUID | None, filename: str, sudo: bool = False) -> dict` — validates and runs a workspace `.sh`.
- `_run_shell_op` keeps its own validation (shell_enabled, command required, sudo gate) then delegates to `_exec_shell_command(... command=command, sudo=sudo, interactive=interactive, caps=caps)`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_run_script.py`:

```python
# Uses the project's existing async test harness + a fake caps with
# shell_enabled=True, shell_sudo=False (mirror test_tools_api.py fixtures).
async def test_run_workspace_script_executes_and_returns_stdout(...):
    # write echo-script into the operator workspace via ws, then:
    out = await service.run_workspace_script(session, user_id=UID,
        conversation_id=None, filename="hello.sh", sudo=False)
    assert out["ok"] and "KAI_RAN_OK" in out["stdout"]

async def test_run_workspace_script_rejects_traversal(...):
    for bad in ["../../etc/passwd", "/etc/passwd", "../x.sh"]:
        out = await service.run_workspace_script(session, user_id=UID,
            conversation_id=None, filename=bad)
        assert out["status"] == "error" and out["reason"] == "bad_script"

async def test_run_workspace_script_requires_sh_extension(...):
    # create "note.txt" in workspace
    out = await service.run_workspace_script(..., filename="note.txt")
    assert out["reason"] == "bad_script"

async def test_run_workspace_script_sudo_blocked_when_disabled(...):
    # caps.shell_sudo False
    out = await service.run_workspace_script(..., filename="hello.sh", sudo=True)
    assert out["status"] == "blocked" and out["reason"] == "sudo_disabled"

async def test_run_workspace_script_name_with_space(...):
    # "a b.sh" exists and echoes; must run (contained by ./ + safe relname)
    out = await service.run_workspace_script(..., filename="a b.sh")
    assert out["ok"]
```

- [ ] **Step 2: Run tests, verify they fail** (`run_workspace_script` undefined / AttributeError).
  Run: `cd backend && python -m pytest tests/test_run_script.py -v`

- [ ] **Step 3: Refactor `_run_shell_op`** — move the body from the rate-limit check (~line 291) through the `return out` (~line 373) into `_exec_shell_command(...)`, parameterised on `command, sudo, interactive, caps, extra_args`. `extra_args` is merged into the recorded `args` dict (so a script run records `{"command","sudo","interactive","script": filename}`). `_run_shell_op` keeps its validation then calls the helper. Keep the returned dict shape byte-identical for the shell path.

- [ ] **Step 4: Implement `run_workspace_script`**:
  - `if not caps.shell_enabled: return {...reason:"shell_disabled"...}` (reuse the `_run_shell_op` message).
  - `base = ws.operator_dir(user_id)`; `rel = ws._safe_relname(filename)`; `path = (base / rel).resolve()`.
  - Reject if `not str(path).startswith(str(base.resolve()))`, `not path.is_file()`, or `path.suffix != ".sh"` → `{"ok": False, "status": "error", "reason": "bad_script", "operation": SHELL_OP_KEY, "message": "No such script in the workspace (must be a .sh file you can see in Assets)."}`.
  - `if sudo and not caps.shell_sudo: return {...reason:"sudo_disabled"...}` (reuse message).
  - `command = f"bash ./{rel}"`; `return await _exec_shell_command(session, user_id=user_id, conversation_id=conversation_id, command=command, sudo=sudo, interactive=False, caps=caps, extra_args={"script": filename})`.

- [ ] **Step 5: Run tests, verify they pass.** Run: `cd backend && python -m pytest tests/test_run_script.py -v`

- [ ] **Step 6: Run the shell + tools suites to prove no regression.** Run: `cd backend && python -m pytest tests/test_security_tools.py tests/test_tools_api.py -q`

- [ ] **Step 7: Commit** `feat(shell): shared shell executor + workspace .sh runner`.

---

## Task 2: `/tools/run-script` API route

**Files:**
- Modify: `backend/app/api/tools.py` (add body model + route near the install routes)
- Test: `backend/tests/test_tools_api.py` (add cases)

**Interfaces:**
- Consumes: `service.run_workspace_script` (Task 1); `get_current_operator`, `get_session`.
- Produces: `POST /tools/run-script` with body `{filename: str, sudo: bool = False, conversation_id: uuid.UUID | None = None}` → the dict from `run_workspace_script`.

- [ ] **Step 1: Write failing tests** in `test_tools_api.py`:

```python
async def test_run_script_requires_auth(client):
    r = await client.post("/tools/run-script", json={"filename": "x.sh"})
    assert r.status_code == 401

async def test_run_script_runs_workspace_script(auth_client, ...):
    # write hello.sh into the operator workspace, then:
    r = await auth_client.post("/tools/run-script", json={"filename": "hello.sh"})
    assert r.status_code == 200 and r.json()["ok"]

async def test_run_script_bad_name_is_handled(auth_client):
    r = await auth_client.post("/tools/run-script", json={"filename": "../../etc/passwd"})
    assert r.status_code == 200 and r.json()["reason"] == "bad_script"
```

- [ ] **Step 2: Run tests, verify they fail** (404 route missing). Run: `cd backend && python -m pytest tests/test_tools_api.py -k run_script -v`

- [ ] **Step 3: Implement the route** — `RunScriptBody(BaseModel)` and:
```python
@router.post("/run-script")
async def run_script(body: RunScriptBody,
                     operator: User = Depends(get_current_operator),
                     session: AsyncSession = Depends(get_session)) -> dict:
    return await service.run_workspace_script(
        session, user_id=operator.id, conversation_id=body.conversation_id,
        filename=body.filename, sudo=body.sudo)
```

- [ ] **Step 4: Run tests, verify they pass.** Run: `cd backend && python -m pytest tests/test_tools_api.py -k run_script -v`

- [ ] **Step 5: Commit** `feat(api): POST /tools/run-script`.

---

## Task 3: Orchestrator prompt regression test (never-list rule)

**Files:**
- Test: `backend/tests/test_orchestrator_prompt.py` (create, or add to an existing orchestrator test file if one exists)

**Interfaces:**
- Consumes: the function in `security/orchestrator.py` that assembles the shell/agent system message (the one containing the "MISSING TOOL → INSTALL IT" text, ~lines 512–560). Call it the same way existing orchestrator tests build a system prompt; if no public builder is exposed, assert against the module-level prompt text it concatenates.

- [ ] **Step 1: Write the test** — assert the assembled shell system prompt contains both `"missing_tools.txt"` (as the forbidden artefact) and an install instruction (`"INSTALL IT"`), so the rule can't be silently dropped:

```python
def test_prompt_forbids_missing_tools_list():
    msg = orchestrator._shell_system_message(caps=_caps(shell_sudo=True,
        shell_auto_run=True))  # use the real builder name
    text = msg.content
    assert "missing_tools.txt" in text
    assert "INSTALL IT" in text
```
(If the builder name/signature differs, match the real one — read the file first.)

- [ ] **Step 2: Run it, verify it passes** against the current prompt (this is a guard, not a red/green feature). Run: `cd backend && python -m pytest tests/test_orchestrator_prompt.py -v`

- [ ] **Step 3: Commit** `test(orchestrator): guard the never-list-missing-tools rule`.

---

## Task 4: `tools.ts` — `runScript` client

**Files:**
- Modify: `frontend/src/lib/tools.ts`

**Interfaces:**
- Produces: `toolsApi.runScript(body: { filename: string; sudo?: boolean; conversation_id?: string }) => Promise<RunScriptResult>` and `export interface RunScriptResult { ok: boolean; status: string; reason?: string; stdout?: string; exit_code?: number | null; running?: boolean; message?: string; }`.
- Consumes: the existing `api.post` helper and `ToolInfo` (already has `installed`, `source`, `package`, `apt_available`, `operations` — no change needed).

- [ ] **Step 1: Add the type and method** next to `installNow` (POST `/tools/run-script`).
- [ ] **Step 2: Typecheck.** Run: `cd frontend && pnpm tsc --noEmit`
- [ ] **Step 3: Commit** `feat(web): tools.runScript client`.

---

## Task 5: Capability Palette surfaces installable tools

**Files:**
- Modify: `frontend/src/components/chat/CapabilityPalette.tsx`

**Interfaces:**
- Consumes: `toolsApi.inventory()` (already called), `toolsApi.installNow` (existing), `ToolInfo` fields `installed`, `source`, `package`, `apt_available`.
- Produces: no new exports; `scaffoldPrompt` unchanged.

- [ ] **Step 1: Extend `Cap`** with `installed: boolean; source: string; aptAvailable: boolean`. In the inventory effect, stop `if (!t.installed) continue;` — instead include every tool's operations (installed and not), setting these fields. Keep `CORE` builtins as `installed: true`. Dedup by op key as today (installed wins if duplicated).

- [ ] **Step 2: Group collapse state** — add `const [open, setOpen] = useState<Record<string, boolean>>({})`. A group is open when: it has ≥1 installed cap, OR the user toggled it open, OR a search filter is active. Render each group header as a button toggling `open[group]`; show a chevron and the count. Collapsed groups render only the header.

- [ ] **Step 3: Render not-installed caps** — muted style; to the right:
  - `source === "apt" && aptAvailable` → an inline `Install` button (small), calling `toolsApi.installNow({ capability: cap.key.split(".")[0] })`… **note:** install takes a *tool name*, not an op key. Carry the tool name onto `Cap` (`tool: t.name`) in Step 1 and call `installNow({ capability: cap.tool })`. On success, re-run the inventory fetch (extract it into a `load()` callback) so the cap flips to installed/runnable.
  - otherwise (go/pip/github/gem/kali) → a muted `via <source>` tag; clicking the row scaffolds `"Install <cap.tool> for me"` via `onPick` instead of the normal prompt.
  - installed caps behave exactly as today (`onPick(scaffoldPrompt(cap))`).

- [ ] **Step 4: Inline install state** — per-tool `installing`/`error` local state (a small child component like `InstallChip`, mirroring `InstallNow` in Chat.tsx: Spinner while busy, error note on failure, polkit popup happens server-side). Reuse lucide `Download`/`Loader` icons already available.

- [ ] **Step 5: Manual verification note** — in the plan ledger, confirm by reading the file that: installed groups start open, installable-only groups start collapsed, search still matches across all caps. (No RTL test harness is set up in this repo for this component; rely on `tsc` + the reviewer. If a frontend test setup exists, add a render test asserting an Install button appears for an apt tool with `installed:false`.)

- [ ] **Step 6: Typecheck.** Run: `cd frontend && pnpm tsc --noEmit`
- [ ] **Step 7: Commit** `feat(web): surface installable security tools in the capability palette`.

---

## Task 6: Run button on `.sh` assets

**Files:**
- Modify: `frontend/src/pages/Chat.tsx` (`FileChip`, ~lines 350–362)

**Interfaces:**
- Consumes: `toolsApi.runScript` (Task 4), the conversation id available in `Chat.tsx` scope (thread it into `FileChip` as a prop `conversationId?: string`), `Play`/`Download`/`Spinner` (already imported).
- Produces: no new exports.

- [ ] **Step 1: Thread `conversationId`** into `FileChip` from its render site (`r.files.map(...)` ~line 341) — pass the active conversation id already used by the page.

- [ ] **Step 2: Add Run affordance** — when `f.name.toLowerCase().endsWith(".sh")`, render a Run button (lucide `Play`) and a small `root` toggle (a checkbox or a two-state chip) next to Download. Keep Download as-is; the chip becomes a row with actions rather than a single button (don't nest buttons — split the download action and the run action into sibling buttons).

- [ ] **Step 3: Wire Run** — on click, `setBusy(true)`, call `toolsApi.runScript({ filename: f.name, sudo: root, conversation_id: conversationId })`. Render the result beneath the chip: a collapsible mono `<pre>` with `stdout` and `exit N`; on `running` show "still running — open the terminal to continue"; on `reason === "sudo_disabled"`/`"bad_script"`/error show the message in the accent colour (mirror `InstallNow`'s note styling).

- [ ] **Step 4: Typecheck.** Run: `cd frontend && pnpm tsc --noEmit`
- [ ] **Step 5: Commit** `feat(web): run generated .sh assets from chat with optional root`.

---

## Final integration

After all tasks: run `cd backend && python -m pytest -q` (full suite vs. baseline) and `cd frontend && pnpm tsc --noEmit`, then the whole-branch review. Merge of `feat/voice-intelligence` into `main` happens at the very end of the overall effort (operator's call), not in this plan.
