# KAI Capabilities Surfacing + Script Run — Design

Sub-project (follow-on to agent routing / mobile chat). Three related gaps the
operator hit, all in the "KAI has my terminal, let it act" direction.

## Problem

1. **Missing security capabilities.** The chat Capability Palette shows only
   tools already installed on the host (`CapabilityPalette.tsx` skips every tool
   where `!t.installed`). The operator's host has shell + web tools, so the
   palette shows "SHELL 1 / WEB 7" and none of the 100+ OSINT/security tools in
   `security/catalog.py`. They look missing.
2. **"Install them, don't list them."** The operator does not want a
   `missing_tools.txt`; they want KAI to install a needed tool (with
   permission — KAI has terminal access). The backend already supports this
   (`install.py`, `/tools/install/*`, install-on-not-found in the orchestrator,
   and the system prompt already forbids `missing_tools.txt`). The gap is that
   the installable tools are not *surfaced* where the operator browses
   capabilities, and the never-list rule should be verified, not extended.
3. **Run a generated `.sh` from chat.** When KAI writes a script via
   `file.write` it appears as a downloadable asset (`FileChip`) with only a
   Download button. The operator wants to run it in place, elevating to root
   via the desktop password popup when the script needs it.

## Goals

- Surface the full catalogue in the palette: installed tools stay runnable;
  not-yet-installed tools appear grouped + collapsed, apt ones with an inline
  Install button (same polkit-popup flow as everywhere else).
- A Run button on `.sh` assets that executes the script in KAI's live terminal,
  with a "run as root" affordance that triggers the polkit password popup, and
  streams the output back into the chat under the asset.
- No regressions to agent routing, the install workflow, or shell safety.

## Non-goals

- No new package sources. KAI still one-click-installs apt only; go/pip/github/
  gem/kali tools are shown for awareness (as today), not one-click installed.
- No change to the shell auto-run / sudo capability gates. Running a script is
  still a shell execution and obeys `caps.shell_sudo` for root.
- Map features and web-search UX (separate sub-projects) are untouched.

## Decisions

- **Reuse, don't rebuild.** Script execution reuses the existing shell path in
  `security/service.py`: non-root → `terminal.exec_in_session` (the persistent
  live session, one per operator); root → the one-shot `pkexec bash -lc …`
  (`run_argv(..., sudo=True)`) that already shows the desktop password prompt.
  Install reuses `install_mod` / `toolsApi.installNow`.
- **Palette shows the catalogue, backend stays the authority.** The palette
  renders installable tools from the same `/tools/inventory` response it already
  fetches (it carries `installed`, `source`, `package`, `available`,
  `operations`). No new inventory fields required.
- **Script run is a dedicated, validated endpoint**, not a model turn — the
  operator clicked a specific asset, so KAI should not re-plan. The endpoint
  validates the path stays inside the operator workspace and the name ends in
  `.sh`.

## Backend

### `security/service.py` — factor a reusable script runner
Extract the existing shell-execution body (the part after validation in the
`shell.run` handler, ~lines 299–370) so a script run and `shell.run` share one
implementation. New coroutine:

```
async def run_workspace_script(
    session, *, user_id: UUID, conversation_id: UUID | None,
    filename: str, sudo: bool = False,
) -> dict
```

- Resolve the operator workspace dir (`workspace.operator_dir(user_id)`), join
  `filename` through `workspace._safe_relname` (no traversal), require the
  resolved path to exist and end in `.sh`; else `{ok: False, status: "error",
  reason: "bad_script"}`.
- Build `command = f"bash ./{safe_rel}"` (relative, run from the workspace cwd —
  matches how assets are created).
- `sudo` obeys `caps.shell_sudo` exactly like `shell.run` (blocked →
  `reason: "sudo_disabled"` message pointing at the Capabilities panel).
- Execute via the SAME two paths `shell.run` uses (pkexec one-shot for sudo,
  `exec_in_session` otherwise), write the same `ToolExecution` + `AuditLog`
  rows (operation `"shell.run"`, args include `script: filename`).
- Return the same shape `shell.run` returns: `{ok, status, stdout, exit_code,
  running, posture, …}`.

Refactor `shell.run` to call the shared inner executor so behaviour is
identical and tested once.

### `api/tools.py` — new route
```
class RunScriptBody(BaseModel):
    filename: str
    sudo: bool = False
    conversation_id: uuid.UUID | None = None

@router.post("/run-script")
async def run_script(body, operator=Depends(get_current_operator), session=…):
    return await service.run_workspace_script(
        session, user_id=operator.id, conversation_id=body.conversation_id,
        filename=body.filename, sudo=body.sudo)
```
Audited (reuses the `ToolExecution`/`AuditLog` written inside the service).

### Orchestrator prompt — verify only
Confirm the existing "MISSING TOOL → INSTALL IT … NEVER write a file that merely
lists missing tools (no `missing_tools.txt`)" rule is intact (it is). Add a
regression test asserting the phrase stays in the system prompt so it can't be
silently dropped. No behavioural change.

## Frontend

### `lib/tools.ts`
Add `toolsApi.runScript({ filename, sudo, conversation_id })` → `POST
/tools/run-script`. Extend the inventory `ToolOperation`/tool types already used
so the palette can read `installed`, `source`, `package`, `available` (fields
already in the response).

### `components/chat/CapabilityPalette.tsx`
- Build `Cap` from **all** inventory tools, not just installed ones; add
  `installed: boolean`, `source: string`, `package: string`, `available:
  boolean` to `Cap`.
- Installed caps render as today (click → scaffold prompt).
- Not-installed caps render in their group but visually muted; each shows an
  Install affordance:
  - `source === "apt" && available` → inline "Install" button calling
    `toolsApi.installNow({ capability })` (polkit popup); on success re-fetch
    inventory so the cap becomes runnable.
  - otherwise → muted tag with the source (e.g. "via pip"); clicking scaffolds
    "Install <tool> for me" so KAI installs it through the terminal.
- Groups that contain only not-installed caps are **collapsed by default**
  (expandable header with the count); groups with installed caps stay expanded.
  Existing search still matches across all caps and auto-expands matches.

### `pages/Chat.tsx` — `FileChip`
- Keep Download. When `f.name` ends in `.sh`, add a **Run** button (the already
  imported `Play` icon) and a small "root" toggle.
- Run → `toolsApi.runScript({ filename: f.name, sudo, conversation_id })`.
  While running show a spinner; render the returned `stdout` (and exit code) in
  a collapsible mono block beneath the chip. If `running` is true (needs input /
  long job) show a "still running — open the terminal to continue" note.
- Errors (`sudo_disabled`, `bad_script`, non-zero exit) render inline in the
  accent colour, same pattern as `InstallNow`.

## Errors

- Script path outside the workspace, missing, or not `.sh` → `bad_script`, shown
  inline; nothing executes.
- `sudo` requested while `caps.shell_sudo` is off → `sudo_disabled` message
  pointing to the Capabilities panel (identical to `shell.run`).
- Install of a non-apt tool from the palette → the existing `_apt_only` 422 is
  surfaced as the muted "via <source>" path, not an Install button, so it can't
  be clicked into a 422.

## Testing

- `run_workspace_script`: runs a real `.sh` in the workspace and returns its
  stdout + exit code; a path-traversal filename (`../../etc/passwd`, `/abs`) is
  rejected as `bad_script`; a non-`.sh` name is rejected; `sudo=True` with
  `shell_sudo` off returns `sudo_disabled`.
- `shell.run` behaviour unchanged after the refactor (existing shell tests pass;
  the shared executor is exercised by both).
- `/tools/run-script` route: 200 with output for a valid script, auth required,
  422/handled error for a bad filename.
- Orchestrator prompt regression: the never-list-missing-tools sentence is
  present in the assembled system prompt.
- Palette (frontend, light): installable tools render with an Install button;
  installed tools render clickable; not-installed-only groups start collapsed.

## Review Focus

- A script name containing shell metacharacters or spaces must not break out of
  `bash ./<name>` — `_safe_relname` plus the relative `./` prefix must contain
  it; test a name with a space and a name with `;`.
- The live `exec_in_session` is shared with `shell.run`; a long script that
  reports `running` must not wedge the session for the next `shell.run`
  (same read-window semantics as today — verify the result surfaces `running`).
- Installing from the palette must refresh inventory so a just-installed tool
  becomes runnable without a full reload.
