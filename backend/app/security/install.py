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

import asyncio
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


# One privileged apt run at a time: concurrent clicks queue here instead of
# fighting over the dpkg lock (which made the second install fail with exit 100).
_INSTALL_LOCK = asyncio.Lock()


async def apt_availability(packages: list[str]) -> dict[str, bool]:
    """One ``apt-cache policy`` call → {package: has an installable candidate}."""
    apt_cache = shutil.which("apt-cache")
    pkgs = []
    for p in dict.fromkeys(packages):
        try:
            pkgs.append(package_name(p))
        except ArgError:
            continue
    if not apt_cache or not pkgs:
        return {}
    r = await run_argv([apt_cache, "policy", *pkgs], timeout=30)
    out: dict[str, bool] = {}
    cur = None
    for line in r.stdout.splitlines():
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            cur = line.rstrip()[:-1]
        elif cur and line.strip().startswith("Candidate:"):
            out[cur] = line.split(":", 1)[1].strip() not in ("", "(none)")
    return out


async def perform_install(package: str, reinstall: bool = False) -> dict:
    """Perform the privileged install of one package. Returns real logs."""
    return await perform_install_many([package], reinstall=reinstall)


async def perform_install_many(packages: list[str], reinstall: bool = False,
                               timeout: int = 1200) -> dict:
    """One privileged apt-get call for one or more validated packages.

    A single call means a single polkit prompt however many packages there are.
    With ``reinstall`` the fixed argv gains ``--reinstall``; nothing else about
    it can be influenced by the caller.
    """
    s = get_settings()
    try:
        pkgs = [package_name(p) for p in packages]
    except ArgError as exc:
        return {"ok": False, "status": "error", "error": str(exc), "log": ""}
    if not pkgs:
        return {"ok": False, "status": "error", "error": "no packages", "log": ""}

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

    # DPkg::Lock::Timeout makes apt WAIT for another apt/dpkg (e.g. unattended
    # upgrades or a manual `apt install`) rather than failing straight away.
    apt_argv = [apt_get, "-o", "DPkg::Lock::Timeout=900", "install", "-y", "--no-install-recommends"]
    if reinstall:
        apt_argv.append("--reinstall")
    apt_argv += pkgs

    env_extra: dict = {}
    if helper == "sudo":
        argv = [helper_path, "-n", *apt_argv]
    else:  # pkexec and friends
        argv = [helper_path, *apt_argv]
        # pkexec needs the graphical-session vars (inherited by the backend
        # service) to reach the desktop polkit agent and show its prompt.
        for k in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
                  "DBUS_SESSION_BUS_ADDRESS", "XDG_SEAT", "XDG_SESSION_ID"):
            v = os.environ.get(k)
            if v:
                env_extra[k] = v

    # Installs can take a while; give apt a generous but bounded window.
    async with _INSTALL_LOCK:
        res = await run_argv(argv, timeout=timeout, max_bytes=500_000, env_extra=env_extra)
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
