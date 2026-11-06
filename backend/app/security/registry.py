"""Backend-managed registry of security tools and their operations.

Each tool declares WHAT it can do (operations), WHAT it needs (args, target
kind), and HOW risky it is (passive / active / disruptive, root required,
authorization required). Operations build an **argv array** from validated
arguments — never a shell string. A few operations have no CLI tool and run a
Python adapter instead (e.g. CVE lookups against a public API).

Availability is DISCOVERED on the real host (``shutil.which`` + a version
probe); a tool is never assumed present just because it is listed here. The
registry is intentionally easy to extend: add a ``ToolSpec`` with operations.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.security import adapters

# posture values
PASSIVE = "passive"
ACTIVE = "active"
DISRUPTIVE = "disruptive"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: str  # domain|host|ip|url|dns_type|port_spec|str|int|bool
    required: bool = True
    default: object = None
    help: str = ""


@dataclass(frozen=True)
class Operation:
    key: str
    tool: str
    title: str
    description: str
    posture: str
    params: list[ParamSpec] = field(default_factory=list)
    requires_authorization: bool = False  # true for ACTIVE scans against targets
    needs_root: bool = False
    timeout_s: int | None = None  # override the default wall-clock cap (slow, bounded scans)
    target_param: str | None = None  # which param is the network target (for auth checks)
    # exactly one of these is set:
    build_argv: Callable[[str, dict], list[str]] | None = None  # (resolved_path, params)->argv
    pyrun: Callable[[dict], Awaitable[dict]] | None = None       # params -> result dict


@dataclass(frozen=True)
class ToolSpec:
    name: str
    purpose: str
    package: str                      # Ubuntu/apt package name
    source: str = "apt"               # install source
    categories: tuple[str, ...] = ()
    needs_root_default: bool = False
    operations: tuple[Operation, ...] = ()
    binary: str = ""                  # executable to discover (defaults to name)

    @property
    def exe(self) -> str:
        return self.binary or self.name


# ───────────────────────── tool definitions ─────────────────────────── #

DIG = ToolSpec(
    name="dig",
    purpose="DNS record inspection (resolve A/AAAA/MX/TXT/NS/SOA/CAA records).",
    package="bind9-dnsutils",
    categories=("domain-intel",),
    operations=(
        Operation(
            key="dns.records",
            tool="dig",
            title="DNS records",
            description="Look up DNS records of a given type for a domain.",
            posture=PASSIVE,
            params=[
                ParamSpec("domain", "domain", help="Domain to query, e.g. example.com"),
                ParamSpec("type", "dns_type", required=False, default="A", help="Record type"),
            ],
            build_argv=adapters.dig_records,
        ),
    ),
)

WHOIS = ToolSpec(
    name="whois",
    purpose="WHOIS/registration lookups for domains and IPs.",
    package="whois",
    categories=("domain-intel",),
    operations=(
        Operation(
            key="whois.lookup",
            tool="whois",
            title="WHOIS lookup",
            description="Registration / ownership metadata for a domain or IP.",
            posture=PASSIVE,
            params=[ParamSpec("target", "host", help="Domain or IP")],
            build_argv=adapters.whois_lookup,
        ),
    ),
)

CURL = ToolSpec(
    name="curl",
    purpose="HTTP response and security-header inspection.",
    package="curl",
    categories=("domain-intel", "web"),
    operations=(
        Operation(
            key="http.headers",
            tool="curl",
            title="HTTP headers",
            description="Fetch response headers and status (checks security headers).",
            posture=PASSIVE,
            params=[ParamSpec("url", "url", help="http(s) URL")],
            target_param="url",
            build_argv=adapters.curl_headers,
        ),
    ),
)

OPENSSL = ToolSpec(
    name="openssl",
    purpose="TLS certificate and configuration inspection.",
    package="openssl",
    categories=("domain-intel", "tls"),
    operations=(
        Operation(
            key="tls.inspect",
            tool="openssl",
            title="TLS certificate",
            description="Inspect the TLS certificate and chain presented on :443.",
            posture=PASSIVE,
            params=[
                ParamSpec("host", "host", help="Hostname, e.g. example.com"),
                ParamSpec("port", "port_spec", required=False, default="443", help="TLS port"),
            ],
            build_argv=adapters.openssl_tls,
        ),
    ),
)

NMAP = ToolSpec(
    name="nmap",
    purpose="Authorized network and service discovery.",
    package="nmap",
    categories=("assessment",),
    operations=(
        Operation(
            key="nmap.service_scan",
            tool="nmap",
            title="Service/version scan (authorized)",
            description=(
                "TCP connect service/version scan of specific ports on an AUTHORIZED "
                "target. Uses -sT (no root), -Pn, safe timing. Active — requires the "
                "target to be on the operator's authorized list."
            ),
            posture=ACTIVE,
            requires_authorization=True,
            target_param="target",
            params=[
                ParamSpec("target", "host", help="Authorized host or IP"),
                ParamSpec("ports", "port_spec", required=False, default="22,80,443",
                          help="Ports, e.g. 22,80,443 or 1-1024"),
            ],
            build_argv=adapters.nmap_service_scan,
        ),
    ),
)

JOURNAL = ToolSpec(
    name="journalctl",
    purpose="Local authentication / system log analysis.",
    package="systemd",
    categories=("logs",),
    operations=(
        Operation(
            key="logs.ssh_auth",
            tool="journalctl",
            title="SSH auth events",
            description="Recent sshd authentication events from the local journal (read-only).",
            posture=PASSIVE,
            params=[ParamSpec("lines", "int", required=False, default=500, help="Max log lines")],
            build_argv=adapters.journal_ssh,
        ),
    ),
)

UFW = ToolSpec(
    name="ufw",
    purpose="Host firewall status inspection.",
    package="ufw",
    categories=("logs", "host"),
    needs_root_default=True,
    operations=(
        Operation(
            key="firewall.status",
            tool="ufw",
            title="Firewall status",
            description="Show the host firewall (ufw) ruleset and status (read-only).",
            posture=PASSIVE,
            needs_root=True,
            params=[],
            build_argv=adapters.ufw_status,
        ),
    ),
)

CVE = ToolSpec(
    name="osv",
    purpose="Public vulnerability advisory / CVE research (OSV.dev, keyless).",
    package="",  # no CLI tool; built-in Python adapter
    source="builtin",
    categories=("vuln-research",),
    operations=(
        Operation(
            key="cve.lookup",
            tool="osv",
            title="Vulnerability advisories",
            description="Query public advisories for a package@version via OSV.dev.",
            posture=PASSIVE,
            params=[
                ParamSpec("ecosystem", "str", help="e.g. PyPI, npm, Debian, Go"),
                ParamSpec("package", "str", help="Package name"),
                ParamSpec("version", "str", required=False, default="", help="Version (optional)"),
            ],
            pyrun=adapters.osv_lookup,
        ),
    ),
)


WEB = ToolSpec(
    name="web",
    purpose=("General open-web research + reading one page's content, clearnet "
            "or a Tor hidden service (.onion) — keyless, built-in Python."),
    package="",  # no CLI tool; built-in Python adapters
    source="builtin",
    categories=("web-intel",),
    operations=(
        Operation(
            key="web.search",
            tool="web",
            title="Web search",
            description=("Search the open web (DuckDuckGo-over-Tor / SearXNG / Mojeek pool) "
                        "for candidate sources on a topic. Returns URLs, not content — "
                        "follow up with web.fetch to read one."),
            posture=PASSIVE,
            params=[ParamSpec("query", "str", help="search query")],
            pyrun=adapters.web_search,
        ),
        Operation(
            key="web.fetch",
            tool="web",
            title="Fetch a web page",
            description=("Read ONE public page's text. Works on a normal URL or a .onion "
                        "address (routed through the system Tor service automatically). "
                        "SSRF-guarded: private/internal addresses are refused. Read-only — "
                        "never submits forms or logs in."),
            posture=PASSIVE,
            params=[ParamSpec("url", "url", help="http(s) URL, or a .onion address")],
            target_param="url",
            pyrun=adapters.web_fetch,
        ),
    ),
)

METASPLOIT = ToolSpec(
    name="metasploit-framework",
    purpose=("Metasploit module research and non-destructive vulnerability checks. "
            "KAI can search/inspect modules and run a module's 'check' against an "
            "authorized target — it never runs 'exploit'/'run' or generates a payload."),
    package="metasploit-framework",
    source="kali",
    categories=("support", "vuln-research"),
    binary="msfconsole",
    operations=(
        Operation(
            key="msf.search",
            tool="metasploit-framework",
            title="Search the module database",
            description="Search Metasploit's local module database (read-only, no target).",
            posture=PASSIVE,
            params=[ParamSpec("query", "term", help="search term, e.g. 'eternalblue' or 'type:exploit apache'")],
            timeout_s=60,
            build_argv=adapters.msf_search,
        ),
        Operation(
            key="msf.info",
            tool="metasploit-framework",
            title="Show info for a module",
            description="Show a module's info (description, options, targets, references).",
            posture=PASSIVE,
            params=[ParamSpec("module", "term", help="module path, e.g. exploit/windows/smb/ms17_010_eternalblue")],
            timeout_s=60,
            build_argv=adapters.msf_info,
        ),
        Operation(
            key="msf.check",
            tool="metasploit-framework",
            title="Check (authorized, non-destructive)",
            description=(
                "Run a module's built-in 'check' against an AUTHORIZED target: probes "
                "for the vulnerability without exploiting it. Never runs exploit/run."
            ),
            posture=ACTIVE,
            requires_authorization=True,
            target_param="target",
            params=[
                ParamSpec("module", "term", help="module path, e.g. exploit/windows/smb/ms17_010_eternalblue"),
                ParamSpec("target", "host", help="authorized host or IP (sets RHOSTS)"),
            ],
            timeout_s=60,
            build_argv=adapters.msf_check,
        ),
    ),
)

JOHN = ToolSpec(
    name="john",
    purpose=("Offline single-hash cracking attempt against a small built-in "
            "wordlist. No network target — operates only on a hash string the "
            "operator supplies directly."),
    package="john",
    categories=("assessment",),
    operations=(
        Operation(
            key="john.crack",
            tool="john",
            title="Crack a single hash (offline, built-in wordlist)",
            description=("Attempt to crack ONE password hash against john's small "
                        "built-in wordlist. Passive — no host or network is touched."),
            posture=PASSIVE,
            params=[ParamSpec("hash", "hash", help="the password hash to crack")],
            timeout_s=60,
            pyrun=adapters.john_crack,
        ),
    ),
)

HYDRA = ToolSpec(
    name="hydra",
    purpose=("Online SSH credential check against an authorized target, using "
            "a small FIXED built-in user/password list (not operator-suppliable "
            "in this pass) — bounded and auditable, stops at first hit."),
    package="hydra",
    categories=("assessment",),
    operations=(
        Operation(
            key="hydra.ssh_brute",
            tool="hydra",
            title="SSH credential check (authorized, built-in list)",
            description=("Try a small fixed set of common SSH username/password pairs "
                        "against an AUTHORIZED target. Active — requires authorization. "
                        "Stops at the first successful pair; hard-capped runtime."),
            posture=ACTIVE,
            requires_authorization=True,
            target_param="target",
            params=[ParamSpec("target", "host", help="authorized host or IP")],
            timeout_s=45,
            build_argv=adapters.hydra_ssh_brute,
        ),
    ),
)

_CORE_TOOLS: tuple[ToolSpec, ...] = (
    DIG, WHOIS, CURL, OPENSSL, NMAP, JOURNAL, UFW, CVE, WEB, METASPLOIT, JOHN, HYDRA,
)


# ───────────────── catalogue → ToolSpec builder ───────────────── #
def _make_templated(opdef: dict) -> Callable[[str, dict], list[str]]:
    """Build an argv from fixed template strings + one validated target. All
    flags come from the catalogue (trusted); only the target is user-supplied."""
    from app.security import validate as V

    target = opdef.get("target")
    template = list(opdef.get("template", []))

    def build(path: str, params: dict) -> list[str]:
        tval = None
        if target:
            tval = V.by_kind(target["kind"], params.get(target["name"], ""))
        argv = [path]
        for tok in template:
            argv.append(tval if tok == "{target}" else tok)
        return argv

    return build


def _spec_from_catalogue(entry: dict) -> ToolSpec:
    ops: list[Operation] = []
    for od in entry.get("ops", []):
        tgt = od.get("target")
        params = []
        if tgt:
            params = [ParamSpec(tgt["name"], tgt["kind"], help=f"{tgt['kind']} target")]
        posture = od.get("posture", PASSIVE)
        ops.append(Operation(
            key=od["key"],
            tool=entry["name"],
            title=od.get("title", od["key"]),
            description=od.get("desc", entry.get("purpose", "")),
            posture=posture,
            params=params,
            requires_authorization=bool(od.get("auth", posture in (ACTIVE, DISRUPTIVE) and od.get("auth", False))),
            needs_root=bool(od.get("root", False)),
            timeout_s=od.get("timeout"),
            target_param=tgt["name"] if tgt else None,
            build_argv=_make_templated(od),
        ))
    return ToolSpec(
        name=entry["name"],
        purpose=entry.get("purpose", ""),
        package=entry.get("package", ""),
        source=entry.get("source", "apt"),
        categories=tuple(entry.get("categories", ())),
        needs_root_default=bool(entry.get("root", False)),
        operations=tuple(ops),
        binary=entry.get("binary", ""),
    )


# Operator-defined tools (catalogue-shaped dicts), merged in after the built-in
# catalogue. Populated from the DB at startup via app.security.custom_tools and
# refreshed whenever the operator adds/edits/removes a capability.
_CUSTOM_ENTRIES: list[dict] = []


def _build_all() -> tuple[ToolSpec, ...]:
    from app.security.catalog import CATALOG

    by_name: dict[str, ToolSpec] = {t.name: t for t in _CORE_TOOLS}
    for entry in CATALOG:
        if entry["name"] in by_name:
            continue  # core tools win
        by_name[entry["name"]] = _spec_from_catalogue(entry)
    for entry in _CUSTOM_ENTRIES:
        name = entry.get("name")
        if not name or name in by_name:
            continue  # never override a core/catalogue tool
        try:
            by_name[name] = _spec_from_catalogue(entry)
        except Exception:  # noqa: BLE001 — a bad custom entry must not break the registry
            continue
    return tuple(by_name.values())


ALL_TOOLS: tuple[ToolSpec, ...] = _build_all()

_TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
_OPS_BY_KEY = {op.key: (t, op) for t in ALL_TOOLS for op in t.operations}


def _rebuild() -> None:
    global ALL_TOOLS, _TOOLS_BY_NAME, _OPS_BY_KEY
    ALL_TOOLS = _build_all()
    _TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
    _OPS_BY_KEY = {op.key: (t, op) for t in ALL_TOOLS for op in t.operations}


def set_custom_tools(entries: list[dict]) -> None:
    """Replace the set of operator-defined tools and rebuild the registry."""
    global _CUSTOM_ENTRIES
    _CUSTOM_ENTRIES = list(entries or [])
    _rebuild()


def reserved_names() -> set[str]:
    """Tool names that a custom capability may NOT reuse (core + catalogue)."""
    from app.security.catalog import CATALOG

    return {t.name for t in _CORE_TOOLS} | {e["name"] for e in CATALOG}


def reserved_op_keys() -> set[str]:
    """Operation keys already in use by non-custom tools."""
    custom = {e.get("name") for e in _CUSTOM_ENTRIES}
    return {
        op.key for t in ALL_TOOLS if t.name not in custom for op in t.operations
    }


def get_tool(name: str) -> ToolSpec | None:
    return _TOOLS_BY_NAME.get(name)


def get_operation(key: str) -> tuple[ToolSpec, Operation] | None:
    return _OPS_BY_KEY.get(key)


def all_operations() -> list[tuple[ToolSpec, Operation]]:
    return list(_OPS_BY_KEY.values())


# ───────────────────────── host discovery ───────────────────────────── #

@dataclass
class Discovered:
    name: str
    installed: bool
    path: str | None
    version: str | None


def which(name: str) -> str | None:
    """Find a tool in the SAME system directories the executor runs with, so KAI only
    ever uses system (apt) installs — never a conda/cargo/~/.local copy that happens to be
    earlier on the backend service's own PATH."""
    from app.security.executor import _SAFE_ENV

    return shutil.which(name, path=_SAFE_ENV["PATH"])


async def discover(tool: ToolSpec) -> Discovered:
    """Discover a tool's real presence and version on this host."""
    if tool.source == "builtin":
        return Discovered(name=tool.name, installed=True, path="(builtin)", version="builtin")
    path = which(tool.exe)
    if not path:
        return Discovered(name=tool.name, installed=False, path=None, version=None)
    version = await adapters.probe_version(tool.exe, path)
    return Discovered(name=tool.name, installed=True, path=path, version=version)
