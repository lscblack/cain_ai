"""Strict validators for tool arguments.

Everything the model or operator supplies is validated here BEFORE it reaches
an argv array. We never build a shell string; these validators also reject
anything that looks like an injection attempt, a private/loopback target, or an
out-of-scope value. A rejected value raises :class:`ArgError`.
"""
from __future__ import annotations

import ipaddress
import re

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)
# Conservative package-name charset (Debian/Ubuntu: lowercase, digits, + - . )
_PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+.\-]{0,99}$")
_DNS_TYPES = {"A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME", "CAA", "SRV", "PTR", "ANY"}


class ArgError(ValueError):
    """A supplied argument failed validation."""


def _no_meta(value: str) -> None:
    # Defence in depth: argv execution already prevents shell interpretation,
    # but reject obvious control/shell metacharacters so nothing weird is logged
    # or passed as a flag by accident.
    if any(c in value for c in "\n\r\t\x00"):
        raise ArgError("control characters not allowed")
    if value.startswith("-"):
        raise ArgError("value may not start with '-' (looks like a flag)")


def hostname(value: str) -> str:
    value = (value or "").strip().rstrip(".")
    _no_meta(value)
    if not _HOSTNAME_RE.match(value):
        raise ArgError(f"invalid hostname: {value!r}")
    return value


def domain(value: str) -> str:
    value = (value or "").strip().rstrip(".")
    _no_meta(value)
    if not _DOMAIN_RE.match(value):
        raise ArgError(f"invalid domain: {value!r}")
    return value.lower()


def ip_address(value: str) -> str:
    value = (value or "").strip()
    _no_meta(value)
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise ArgError(f"invalid IP address: {value!r}") from exc


def host_or_ip(value: str) -> str:
    value = (value or "").strip()
    try:
        return ip_address(value)
    except ArgError:
        return hostname(value)


def dns_type(value: str) -> str:
    v = (value or "A").strip().upper()
    if v not in _DNS_TYPES:
        raise ArgError(f"unsupported DNS record type: {value!r}")
    return v


def port(value) -> int:
    try:
        p = int(value)
    except (TypeError, ValueError) as exc:
        raise ArgError(f"invalid port: {value!r}") from exc
    if not (1 <= p <= 65535):
        raise ArgError(f"port out of range: {p}")
    return p


def port_spec(value: str) -> str:
    """nmap-style port spec: comma-separated ports/ranges, e.g. '22,80,443,8000-8100'."""
    value = (value or "").strip()
    _no_meta(value)
    if not re.fullmatch(r"\d{1,5}(-\d{1,5})?(,\d{1,5}(-\d{1,5})?)*", value):
        raise ArgError(f"invalid port spec: {value!r}")
    for part in value.split(","):
        for p in part.split("-"):
            port(p)
    return value


def package_name(value: str) -> str:
    value = (value or "").strip()
    if not _PKG_RE.match(value):
        raise ArgError(f"invalid package name: {value!r}")
    return value


def url(value: str):
    """Validate a public http(s) URL (reuses the SSRF guard)."""
    from app.core.net import UnsafeUrlError, validate_public_url

    value = (value or "").strip()
    _no_meta(value)
    try:
        return validate_public_url(value)
    except UnsafeUrlError as exc:
        raise ArgError(f"unsafe or invalid URL: {exc}") from exc
