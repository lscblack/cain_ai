"""SSRF-safe URL validation.

Any operator-supplied URL that KAI will fetch (crawler, reverse-image
providers, enrichment) MUST pass through :func:`validate_public_url` first.
It is shipped in Phase 1 — before any fetcher exists — so no later phase can
forget it.

Blocks: non-http(s) schemes; hosts that resolve to loopback, private
(RFC1918), link-local (incl. 169.254.169.254 cloud metadata), unique-local
IPv6, reserved, or unspecified addresses. DNS-rebinding-aware: *every*
resolved address must be public.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}

Resolver = Callable[[str], list[str]]


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe to fetch (SSRF risk / malformed)."""


@dataclass(frozen=True)
class SafeUrl:
    url: str
    scheme: str
    host: str
    port: int | None
    resolved_ips: tuple[str, ...]


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def _ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str.split("%")[0])  # strip zone id
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_url(url: str, *, resolver: Resolver | None = None) -> SafeUrl:
    resolver = resolver or _default_resolver

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme not allowed: {scheme or '(none)'}")

    host = parts.hostname
    if not host:
        raise UnsafeUrlError("missing host")

    # If the host is itself a literal IP, check it directly.
    try:
        literal = ipaddress.ip_address(host)
        if not _ip_is_public(str(literal)):
            raise UnsafeUrlError(f"non-public address: {host}")
        resolved = [str(literal)]
    except ValueError:
        if host.lower() == "localhost":
            raise UnsafeUrlError("localhost blocked")
        try:
            resolved = resolver(host)
        except OSError as exc:
            raise UnsafeUrlError(f"cannot resolve host: {host}") from exc
        if not resolved:
            raise UnsafeUrlError(f"host did not resolve: {host}")
        for ip in resolved:
            if not _ip_is_public(ip):
                raise UnsafeUrlError(f"host resolves to non-public address: {ip}")

    return SafeUrl(
        url=url,
        scheme=scheme,
        host=host,
        port=parts.port,
        resolved_ips=tuple(resolved),
    )
