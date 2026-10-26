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
    raw = str(params.get("domain", ""))
    # tolerate a pasted URL — extract the host, then validate as a domain
    domain = V.domain(V.target_host(raw) if "://" in raw or "/" in raw else raw)
    rtype = V.dns_type(params.get("type", "A"))
    # +nocmd/+noall/+answer → terse, parseable answer section only.
    return [path, "+nocmd", "+noall", "+answer", "+time=5", "+tries=2", domain, rtype]


def whois_lookup(path: str, params: dict) -> list[str]:
    target = V.target_host(params.get("target", ""))
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
    host = V.target_host(params.get("host", ""))
    ports = V.port_spec(str(params.get("port", "443")))
    port = ports.split(",")[0].split("-")[0]
    V.port(port)
    # s_client with empty stdin (executor passes b"") closes after handshake.
    return [
        path, "s_client", "-connect", f"{host}:{port}", "-servername", host,
        "-brief",
    ]


def nmap_service_scan(path: str, params: dict) -> list[str]:
    target = V.target_host(params.get("target", ""))
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


def msf_search(path: str, params: dict) -> list[str]:
    term = V.search_term(params.get("query", ""))
    # -q quiet banner, -x run a resource-script string then exit. search_term()
    # already rejects ; | & $ ` < > \ etc., so this can't smuggle extra msf commands.
    return [path, "-q", "-x", f"search {term}; exit"]


def msf_info(path: str, params: dict) -> list[str]:
    module = V.search_term(params.get("module", ""))
    return [path, "-q", "-x", f"info {module}; exit"]


def msf_check(path: str, params: dict) -> list[str]:
    # Non-destructive only: 'check' probes for the vulnerability without exploiting
    # it. No 'exploit'/'run' command is ever built here.
    module = V.search_term(params.get("module", ""))
    target = V.target_host(params.get("target", ""))
    return [path, "-q", "-x", f"use {module}; set RHOSTS {target}; check; exit"]


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
    # Known flag, else a best-effort generic --version.
    args = _VERSION_ARGS.get(name, ["--version"])
    try:
        proc = await asyncio.create_subprocess_exec(
            path, *args,
            stdin=asyncio.subprocess.DEVNULL,  # never block on stdin
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
    except (OSError, asyncio.TimeoutError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        return None
    text = (out or b"").decode("utf-8", "replace").strip()
    if not text:
        return None
    first = text.splitlines()[0][:200]
    # Guard against a tool that printed a usage/error instead of a version.
    return first if len(first) < 200 else None


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


_HYDRA_USERS = ["admin", "root", "test", "ubuntu", "administrator"]
_HYDRA_PASSWORDS = ["admin", "password", "123456", "root", "changeme", "test123", "letmein"]
_JOHN_WORDLISTS = ("/usr/share/john/password.lst", "/usr/share/dict/words")


def hydra_ssh_brute(path: str, params: dict) -> list[str]:
    """Online SSH credential check against an AUTHORIZED target only, using a
    small FIXED built-in user/pass list (no operator-suppliable wordlists in
    this pass — keeps it bounded and auditable). -f stops at the first hit;
    -t/-w cap concurrency and per-attempt wait so this can't run unbounded."""
    import os

    from app.security.executor import _TOOL_HOME

    target = V.target_host(params.get("target", ""))
    users_path = os.path.join(_TOOL_HOME, "hydra-users.txt")
    pass_path = os.path.join(_TOOL_HOME, "hydra-passwords.txt")
    with open(users_path, "w") as f:
        f.write("\n".join(_HYDRA_USERS) + "\n")
    with open(pass_path, "w") as f:
        f.write("\n".join(_HYDRA_PASSWORDS) + "\n")
    return [
        path, "-L", users_path, "-P", pass_path, "-t", "4", "-w", "10", "-f",
        f"ssh://{target}",
    ]


async def john_crack(params: dict) -> dict:
    """Offline single-hash cracking attempt (john). No network target — the
    operator supplies the hash itself. Uses the small built-in wordlist that
    ships with john (or the system dictionary as a fallback); does NOT accept
    an operator-supplied wordlist path in this pass."""
    import os
    import uuid as _uuid

    from app.security import registry
    from app.security.executor import _TOOL_HOME, run_argv

    hash_str = V.hash_value(params.get("hash", ""))
    john_path = registry.which("john")
    if not john_path:
        raise RuntimeError("john is not installed")
    wordlist = next((w for w in _JOHN_WORDLISTS if os.path.exists(w)), None)
    if not wordlist:
        raise RuntimeError("no built-in wordlist found on this host (expected john's own password.lst)")

    hash_path = os.path.join(_TOOL_HOME, f"john-{_uuid.uuid4().hex}.hash")
    with open(hash_path, "w") as f:
        f.write(hash_str + "\n")
    try:
        crack = await run_argv(
            [john_path, f"--wordlist={wordlist}", hash_path], timeout=40, max_bytes=50_000,
        )
        show = await run_argv([john_path, "--show", hash_path], timeout=10, max_bytes=50_000)
    finally:
        try:
            os.remove(hash_path)
        except OSError:
            pass
    show_out = show.stdout or ""
    cracked = ":" in show_out and "0 password hash" not in show_out
    password = show_out.split(":", 2)[1] if cracked and show_out.count(":") >= 1 else None
    return {
        "hash": hash_str,
        "wordlist": wordlist,
        "cracked": bool(cracked and password),
        "password": password,
        "john_output": (crack.stdout or "")[:2000],
    }


async def web_search(params: dict) -> dict:
    """Open-web search (keyless engine pool: DuckDuckGo-over-Tor, SearXNG,
    Mojeek — see app.discovery.search) for general research during an
    investigation. Returns candidate domains/URLs with provenance; use
    web.fetch to actually read one."""
    from app.discovery.search import search_candidates_free

    query = str(params.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")

    found = await search_candidates_free([query], concurrency=1)
    results = [{"domain": dom, "url": url} for dom, url in list(found.items())[:15]]
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "note": "Candidate sources only — use web.fetch on a specific URL to read its content.",
    }


async def web_fetch(params: dict) -> dict:
    """Fetch and read ONE public page's text (clearnet or a .onion hidden
    service, routed via Tor automatically — see app.crawlers.http). SSRF-guarded
    (app.core.net.validate_public_url): private/internal addresses are refused.
    Read-only — never submits forms, logs in, or interacts with a site."""
    from app.core.net import UnsafeUrlError, validate_public_url
    from app.crawlers.extract import extract_page_meta, extract_text_excerpt
    from app.crawlers.http import httpx_fetch

    url = str(params.get("url", "")).strip()
    if not url:
        raise ValueError("url is required")
    try:
        validate_public_url(url)
    except UnsafeUrlError as exc:
        raise ValueError(f"refused: {exc}") from exc

    fetched = await httpx_fetch(url)
    if fetched.status == 0:
        host = url.split("/")[2] if "//" in url else url
        reason = "Tor is required to reach .onion addresses and is not configured" \
            if host.endswith(".onion") else "could not be reached (SSRF-blocked, proxy required, or unreachable)"
        return {"ok": False, "url": url, "status": 0, "error": reason}
    if fetched.status != 200:
        return {"ok": False, "url": url, "status": fetched.status,
                "content_type": fetched.content_type}

    is_text = fetched.content_type.startswith(("text/", "application/xhtml", "application/json"))
    if not is_text:
        return {"ok": True, "url": url, "status": 200, "content_type": fetched.content_type,
                "note": "non-text content — not extracted", "size_bytes": len(fetched.body)}

    html = fetched.body.decode("utf-8", errors="replace")
    meta = extract_page_meta(html) if "html" in fetched.content_type else {}
    text = extract_text_excerpt(html, max_len=3000) or html[:3000]
    return {
        "ok": True,
        "url": url,
        "status": 200,
        "content_type": fetched.content_type,
        "title": meta.get("title"),
        "text": text,
        "truncated": len(html) > 3000,
    }
