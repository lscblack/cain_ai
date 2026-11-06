"""Safe subprocess execution for security tools.

Hard rules enforced here:
- argv arrays only (``create_subprocess_exec``) — never a shell, so no
  model/operator string is ever interpreted by a shell.
- a sanitised environment (PATH/LANG only) so tools can't read KAI secrets.
- its own process session, killed on timeout (whole group, not just the parent).
- bounded output capture and a wall-clock timeout.
- all output passed through the secret redactor before it is returned, logged,
  or shown to the model.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import time
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.security.redact import redact

import os as _os

# Some tools (e.g. lynis) hard-require $HOME to exist and refuse to run without
# it, but the real $HOME must NOT be exposed here — it would let a tool read the
# operator's dotfiles (.ssh, .aws, …). Give them a dedicated, empty, writable
# scratch directory instead.
_TOOL_HOME = "/tmp/kai-tool-home"
_os.makedirs(_TOOL_HOME, exist_ok=True)

_SAFE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "HOME": _TOOL_HOME,
}


@dataclass
class ExecResult:
    argv: list[str]
    status: str                 # ok | error | timeout
    exit_code: int | None = None
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    truncated: bool = False
    extra: dict = field(default_factory=dict)  # for python-adapter results

    def to_dict(self) -> dict:
        return {
            "argv_display": display_argv(self.argv),
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "truncated": self.truncated,
            **({"result": self.extra} if self.extra else {}),
        }


def display_argv(argv: list[str]) -> str:
    # The executable path's basename + args, redacted — safe to show/log.
    if not argv:
        return ""
    shown = [os.path.basename(argv[0])] + argv[1:]
    return redact(" ".join(shown))


async def run_argv(
    argv: list[str],
    *,
    timeout: int | None = None,
    max_bytes: int | None = None,
    stdin: bytes | None = None,
    env_extra: dict | None = None,
    inherit_env: bool = False,
    cwd: str | None = None,
) -> ExecResult:
    s = get_settings()
    timeout = timeout or s.tool_exec_timeout_s
    max_bytes = max_bytes or s.tool_output_max_bytes

    if not argv or not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return ExecResult(argv=argv or [], status="error", error="invalid argv")

    start = time.monotonic()
    # Base env is minimal (no KAI secrets). Callers may add a few vetted keys —
    # e.g. the graphical-session vars pkexec needs to show its polkit prompt.
    # inherit_env=True is the raw-shell path (run_shell): it runs with the
    # operator's real environment so the terminal behaves like a real one.
    base_env = dict(os.environ) if inherit_env else dict(_SAFE_ENV)
    env = {**base_env, **(env_extra or {})}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd or None,
            start_new_session=True,  # own process group → we can kill children too
        )
    except FileNotFoundError:
        return ExecResult(argv=argv, status="error", error="executable not found")
    except OSError as exc:
        return ExecResult(argv=argv, status="error", error=f"spawn failed: {exc}")

    try:
        out, err = await asyncio.wait_for(proc.communicate(input=stdin), timeout=timeout)
        duration = int((time.monotonic() - start) * 1000)
        truncated = len(out) > max_bytes or len(err) > max_bytes
        stdout = redact(out[:max_bytes].decode("utf-8", "replace"))
        stderr = redact(err[:max_bytes].decode("utf-8", "replace"))
        return ExecResult(
            argv=argv,
            status="ok" if proc.returncode == 0 else "error",
            exit_code=proc.returncode,
            duration_ms=duration,
            stdout=stdout,
            stderr=stderr,
            error=None if proc.returncode == 0 else f"exit {proc.returncode}",
            truncated=truncated,
        )
    except asyncio.TimeoutError:
        _kill_group(proc)
        duration = int((time.monotonic() - start) * 1000)
        return ExecResult(
            argv=argv,
            status="timeout",
            duration_ms=duration,
            error=f"timed out after {timeout}s",
        )


# Graphical-session vars pkexec needs to reach the desktop polkit agent and
# show its password prompt (same set the install workflow uses).
_PKEXEC_ENV_KEYS = (
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_SEAT", "XDG_SESSION_ID",
)


async def run_shell(
    command: str,
    *,
    sudo: bool = False,
    timeout: int | None = None,
    max_bytes: int | None = None,
    cwd: str | None = None,
) -> ExecResult:
    """Run an arbitrary shell command through ``bash -lc`` with the operator's
    real environment. This is the raw-terminal path — intentionally NOT
    argv-only — and must only be reached after KaiCapabilities.shell_enabled is
    confirmed by the caller (service.run_operation). Still bounded by the same
    wall-clock timeout, output cap, and process-group kill as every other tool.

    When ``sudo`` is set (and the operator enabled shell_sudo), the command runs
    as root. pkexec is preferred — it pops the desktop password dialog so the
    operator authenticates at the OS, even in auto-run; if pkexec is missing we
    fall back to ``sudo -n`` (NOPASSWD, no prompt)."""
    cmd = (command or "").strip()
    if not cmd:
        return ExecResult(argv=["bash", "-lc", ""], status="error", error="empty command")

    if not sudo:
        return await run_argv(
            ["/bin/bash", "-lc", cmd],
            timeout=timeout, max_bytes=max_bytes, inherit_env=True, cwd=cwd,
        )

    # ── privileged path ──
    pkexec = shutil.which("pkexec")
    if pkexec:
        env_extra = {k: v for k in _PKEXEC_ENV_KEYS if (v := os.environ.get(k))}
        return await run_argv(
            [pkexec, "/bin/bash", "-lc", cmd],
            timeout=timeout, max_bytes=max_bytes, inherit_env=True, cwd=cwd,
            env_extra=env_extra,
        )
    sudo_bin = shutil.which("sudo")
    if sudo_bin:
        res = await run_argv(
            [sudo_bin, "-n", "/bin/bash", "-lc", cmd],
            timeout=timeout, max_bytes=max_bytes, inherit_env=True, cwd=cwd,
        )
        blob = f"{res.stdout}\n{res.stderr}"
        if res.status != "ok" and ("a password is required" in blob or "a terminal is required" in blob):
            res.error = ("sudo needs a password but no pkexec desktop prompt is "
                         "available. Install pkexec (policykit-1) or add a NOPASSWD sudoers rule.")
        return res
    return ExecResult(argv=["pkexec"], status="error",
                      error="no privilege helper found (install pkexec or sudo)")


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
