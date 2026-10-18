"""Tool adapters: turn validated parameters into an argv array (no shell),
plus version probing and the Python-backed OSV vulnerability adapter.

Every builder returns a list[str] whose first element is the resolved absolute
path to the executable. Arguments are validated (see ``validate``) so nothing
operator/model-supplied can smuggle a flag or shell metacharacter.
"""
from __future__ import annotations

import asyncio

from app.security import validate as V

# ───────────────────────── argv builders ────────────────────────────── #


def dig_records(path: str, params: dict) -> list[str]:
    domain = V.domain(params.get("domain", ""))
    rtype = V.dns_type(params.get("type", "A"))
    # +nocmd/+noall/+answer → terse, parseable answer section only.
    return [path, "+nocmd", "+noall", "+answer", "+time=5", "+tries=2", domain, rtype]


def whois_lookup(path: str, params: dict) -> list[str]:
    target = V.host_or_ip(params.get("target", ""))
    return [path, "--", target]


def curl_headers(path: str, params: dict) -> list[str]:
    safe = V.url(params.get("url", ""))
    # -sS quiet but show errors; -I HEAD; -L follow redirects; -D - dump headers;
    # --max-time cap; -A a clear UA so sites don't 403 a blank agent.
    return [
        path, "-sS", "-I", "-L", "--max-redirs", "5", "--max-time", "20",
        "-A", "KAI-Security/1.0 (+https://kai.local)", "--", safe.url,
    ]


def openssl_tls(path: str, params: dict) -> list[str]:
    host = V.host_or_ip(params.get("host", ""))
    ports = V.port_spec(str(params.get("port", "443")))
    port = ports.split(",")[0].split("-")[0]
    V.port(port)
    # s_client with empty stdin (executor passes b"") closes after handshake.
    return [
        path, "s_client", "-connect", f"{host}:{port}", "-servername", host,
        "-brief",
    ]


def nmap_service_scan(path: str, params: dict) -> list[str]:
    target = V.host_or_ip(params.get("target", ""))
    ports = V.port_spec(str(params.get("ports", "22,80,443")))
    # -sT connect scan (no root), -Pn skip host discovery, -sV versions,
    # -T3 polite timing, --host-timeout bounds the run.
    return [
        path, "-sT", "-Pn", "-sV", "-T3", "--host-timeout", "90s",
        "-p", ports, "--", target,
    ]


def journal_ssh(path: str, params: dict) -> list[str]:
    try:
        lines = int(params.get("lines", 500))
    except (TypeError, ValueError):
        lines = 500
    lines = max(1, min(lines, 5000))
    # Read-only: sshd unit, no pager, bounded line count, newest first.
    return [
        path, "--no-pager", "-u", "ssh", "-u", "sshd", "-u", "ssh.service",
        "-n", str(lines), "-o", "short-iso",
    ]


def ufw_status(path: str, params: dict) -> list[str]:
    # 'ufw status verbose' is read-only (needs root to read the ruleset).
    return [path, "status", "verbose"]


# ───────────────────────── version probing ──────────────────────────── #

_VERSION_ARGS: dict[str, list[str]] = {
    "dig": ["-v"],          # prints to stderr
    "whois": ["--version"],
    "curl": ["--version"],
    "openssl": ["version"],
    "nmap": ["--version"],
    "journalctl": ["--version"],
    "ufw": ["version"],
}


async def probe_version(name: str, path: str) -> str | None:
    args = _VERSION_ARGS.get(name)
    if args is None:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except (OSError, asyncio.TimeoutError):
        return None
    text = (out or b"").decode("utf-8", "replace").strip()
    return text.splitlines()[0][:200] if text else None


# ───────────────────────── OSV (CVE research) ───────────────────────── #


async def osv_lookup(params: dict) -> dict:
    """Query OSV.dev for advisories affecting a package (optionally @version).

    Keyless public API. Returns a structured dict; raises RuntimeError on
    transport failure so the executor records an honest error.
    """
    import httpx

    ecosystem = str(params.get("ecosystem", "")).strip()
    package = str(params.get("package", "")).strip()
    version = str(params.get("version", "")).strip()
    if not ecosystem or not package:
        raise ValueError("ecosystem and package are required")

    query: dict = {"package": {"ecosystem": ecosystem, "name": package}}
    if version:
        query["version"] = version

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post("https://api.osv.dev/v1/query", json=query)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"osv request failed: {exc}") from exc

    vulns = data.get("vulns", []) or []
    summary = []
    for v in vulns[:50]:
        summary.append(
            {
                "id": v.get("id"),
                "aliases": v.get("aliases", [])[:8],
                "summary": (v.get("summary") or "")[:300],
                "severity": v.get("severity", []),
                "modified": v.get("modified"),
            }
        )
    return {
        "query": {"ecosystem": ecosystem, "package": package, "version": version or None},
        "count": len(vulns),
        "advisories": summary,
        "source": "https://api.osv.dev/v1/query",
    }
