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


# ───────────────────────── tool definitions ─────────────────────────── #

DIG = ToolSpec(
    name="dig",
    purpose="DNS record inspection (resolve A/AAAA/MX/TXT/NS/SOA/CAA records).",
    package="dnsutils",
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


ALL_TOOLS: tuple[ToolSpec, ...] = (DIG, WHOIS, CURL, OPENSSL, NMAP, JOURNAL, UFW, CVE)

_TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
_OPS_BY_KEY = {op.key: (t, op) for t in ALL_TOOLS for op in t.operations}


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
    return shutil.which(name)


async def discover(tool: ToolSpec) -> Discovered:
    """Discover a tool's real presence and version on this host."""
    if tool.source == "builtin":
        return Discovered(name=tool.name, installed=True, path="(builtin)", version="builtin")
    path = which(tool.name)
    if not path:
        return Discovered(name=tool.name, installed=False, path=None, version=None)
    version = await adapters.probe_version(tool.name, path)
    return Discovered(name=tool.name, installed=True, path=path, version=version)
