"""Persistent, stateful shell sessions for KAI's live terminal.

Each conversation gets one long-lived ``bash`` process (via a pty), so working
directory, environment and running programs persist across ``shell.run`` calls —
the model can ``cd`` once and have later commands run there, and can drive
interactive programs (ssh, python, msfconsole, mysql…) by sending input.

Completion is detected with a unique end-marker appended to each command
(``<cmd> ; printf 'MARK%s\\n' "$?"``). Because the marker is part of the SAME
parsed line as the command, it runs only after the command returns — even if the
command blocked reading stdin — so a later interactive turn still observes the
marker once the program exits. If the marker is not seen within the read window,
the command is reported as still ``running`` and the model can send more input
(``interactive=True``) or read more output (empty command).

pexpect is synchronous, so each turn runs in a worker thread
(:func:`asyncio.to_thread`); a per-session lock serialises access.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading

import pexpect

from app.core.config import get_settings

_MARK = "__KAI_CMD_DONE__"
_MARK_RE = re.compile(re.escape(_MARK) + r"(-?\d+)?")

# How long one read waits for the end-marker before reporting "still running".
_READ_WINDOW_S = 30


class _Session:
    def __init__(self, cwd: str | None) -> None:
        env = dict(os.environ)  # real environment → installed tools on PATH
        env["TERM"] = "dumb"
        env["PAGER"] = "cat"
        env["GIT_PAGER"] = "cat"
        env["PS1"] = ""
        env["PS2"] = ""
        self.child = pexpect.spawn(
            "/bin/bash",
            ["--norc", "--noprofile", "-i"],
            cwd=cwd or None,
            env=env,
            encoding="utf-8",
            codec_errors="replace",
            echo=False,
            dimensions=(50, 160),
            timeout=None,
        )
        self.lock = threading.Lock()

    def alive(self) -> bool:
        try:
            return self.child.isalive()
        except Exception:  # noqa: BLE001
            return False

    def run_blocking(self, command: str, interactive: bool) -> dict:
        with self.lock:
            if not self.alive():
                return {"output": "(terminal session has ended)", "exit_code": None,
                        "finished": True, "running": False, "dead": True}
            try:
                if interactive:
                    # Send raw input to whatever is running (no marker).
                    if command:
                        self.child.send(command + "\n")
                else:
                    # Compound one-liner so the marker runs after the command,
                    # even if the command reads stdin.
                    line = f"{command} ; printf '{_MARK}%s\\n' \"$?\""
                    self.child.send(line + "\n")

                idx = self.child.expect(
                    [_MARK_RE, pexpect.EOF, pexpect.TIMEOUT], timeout=_READ_WINDOW_S
                )
                output = self.child.before or ""
                if idx == 0:  # marker seen → command finished
                    code_str = (self.child.match.group(1) or "").strip()
                    exit_code = int(code_str) if code_str.lstrip("-").isdigit() else None
                    return {"output": output, "exit_code": exit_code,
                            "finished": True, "running": False, "dead": False}
                if idx == 1:  # EOF → shell died
                    return {"output": output, "exit_code": None,
                            "finished": True, "running": False, "dead": True}
                # TIMEOUT → still running / waiting for input
                return {"output": output, "exit_code": None,
                        "finished": False, "running": True, "dead": False}
            except Exception as exc:  # noqa: BLE001
                return {"output": f"(terminal error: {exc})", "exit_code": None,
                        "finished": True, "running": False, "dead": True}

    def close(self) -> None:
        try:
            self.child.close(force=True)
        except Exception:  # noqa: BLE001
            pass


_SESSIONS: dict[str, _Session] = {}
_SESSIONS_GUARD = threading.Lock()


def _get_or_create(key: str, cwd: str | None) -> _Session:
    with _SESSIONS_GUARD:
        sess = _SESSIONS.get(key)
        if sess is None or not sess.alive():
            if sess is not None:
                sess.close()
            sess = _Session(cwd)
            _SESSIONS[key] = sess
        return sess


async def exec_in_session(
    key: str, command: str, *, cwd: str | None = None, interactive: bool = False
) -> dict:
    """Run ``command`` in the persistent session identified by ``key``.

    Returns ``{output, exit_code, finished, running, dead}``. A fresh session is
    created on first use (or if the previous one died), starting in ``cwd``.
    """
    # Allow slow commands a bit more room than the default read window isn't
    # needed here; the read window already balances responsiveness vs. blocking.
    _ = get_settings()  # reserved for future tunables; keeps settings import live
    sess = _get_or_create(key, cwd)
    return await asyncio.to_thread(sess.run_blocking, command or "", interactive)


def close_session(key: str) -> None:
    with _SESSIONS_GUARD:
        sess = _SESSIONS.pop(key, None)
    if sess is not None:
        sess.close()
