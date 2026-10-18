"""Controlled Ubuntu package installation.

The model can propose that a capability's package be installed, but it never
runs a package manager. The flow is: PLAN (read-only inspection) → operator
APPROVAL → PERFORM (a single fixed argv via a scoped privileged helper) →
VERIFY. Nothing is marked installed until verification against the real host
succeeds.

Privileged execution uses ``tool_install_helper`` ("sudo" or "pkexec"). We
never build a shell string and never pass a model-generated command: the argv
is fixed here and only the validated package name varies.
"""
from __future__ import annotations

import os
import shutil

from app.core.config import get_settings
from app.security import registry
from app.security.executor import run_argv
from app.security.validate import ArgError, package_name


async def plan_install(package: str) -> dict:
    """Read-only: is it installed? is it available in apt? candidate version?"""
    try:
        pkg = package_name(package)
    except ArgError as exc:
        return {"ok": False, "error": str(exc)}

    apt_cache = shutil.which("apt-cache")
    dpkg = shutil.which("dpkg")

    already = False
    if dpkg:
        r = await run_argv([dpkg, "-s", pkg], timeout=15)
        already = r.status == "ok" and "Status: install ok installed" in r.stdout

    candidate = None
    available = False
    if apt_cache:
        r = await run_argv([apt_cache, "policy", pkg], timeout=20)
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("Candidate:"):
                candidate = line.split(":", 1)[1].strip()
                available = candidate not in ("", "(none)")
                break

    return {
        "ok": True,
        "package": pkg,
        "already_installed": already,
        "available": available,
        "candidate_version": candidate,
        "source": "apt",
        "needs_root": True,
        "helper": get_settings().tool_install_helper or "(disabled)",
    }


async def perform_install(package: str) -> dict:
    """Perform the privileged install with a fixed argv. Returns real logs."""
    s = get_settings()
    try:
        pkg = package_name(package)
    except ArgError as exc:
        return {"ok": False, "status": "error", "error": str(exc), "log": ""}

    if not s.tool_install_enabled or not s.tool_install_helper:
        return {
            "ok": False,
            "status": "disabled",
            "error": "privileged installation is disabled (tool_install_enabled/helper)",
            "log": "",
        }

    helper = s.tool_install_helper
    helper_path = shutil.which(helper)
    apt_get = shutil.which("apt-get")
    if not helper_path:
        return {"ok": False, "status": "error", "error": f"helper '{helper}' not found", "log": ""}
    if not apt_get:
        return {"ok": False, "status": "error", "error": "apt-get not found", "log": ""}

    env_extra: dict = {}
    if helper == "sudo":
        argv = [helper_path, "-n", apt_get, "install", "-y", "--no-install-recommends", pkg]
    else:  # pkexec and friends
        argv = [helper_path, apt_get, "install", "-y", "--no-install-recommends", pkg]
        # pkexec needs the graphical-session vars (inherited by the backend
        # service) to reach the desktop polkit agent and show its prompt.
        for k in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
                  "DBUS_SESSION_BUS_ADDRESS", "XDG_SEAT", "XDG_SESSION_ID"):
            v = os.environ.get(k)
            if v:
                env_extra[k] = v

    # Installs can take a while; give apt a generous but bounded window.
    res = await run_argv(argv, timeout=600, max_bytes=500_000, env_extra=env_extra)
    log = (res.stdout + "\n" + res.stderr).strip()
    sudo_needs_pw = helper == "sudo" and (
        "a password is required" in log or "a terminal is required" in log
    )
    return {
        "ok": res.status == "ok",
        "status": res.status,
        "exit_code": res.exit_code,
        "error": res.error,
        "log": log[:20000],
        "sudo_needs_password": sudo_needs_pw,
    }


async def verify_tool(tool_name: str) -> dict:
    """Verify an executable works and report its real version."""
    tool = registry.get_tool(tool_name)
    if tool is None:
        # Allow verifying a tool by its executable name even if not a registered spec.
        path = shutil.which(tool_name)
        return {"installed": bool(path), "path": path, "version": None}
    disc = await registry.discover(tool)
    return {"installed": disc.installed, "path": disc.path, "version": disc.version}
