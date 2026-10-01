"""Email intelligence from public signals.

Separates DIRECT EVIDENCE (format, DNS/MX/SPF/DMARC, derivable usernames,
Gravatar URL) from INFERRED relationships. All DNS access goes through an
injectable resolver so the logic is testable offline and so a missing resolver
degrades to 'unavailable' rather than failing.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

_EMAIL_RE = re.compile(r"^(?P<local>[a-z0-9._%+\-]+)@(?P<domain>[a-z0-9.\-]+\.[a-z]{2,})$", re.I)

# resolver(name, rtype) -> list[str]; raises LookupError when nothing / cannot resolve.
DnsResolver = Callable[[str, str], list[str]]


class _ResolverProto(Protocol):  # pragma: no cover - typing aid
    def __call__(self, name: str, rtype: str) -> list[str]: ...


@dataclass
class EmailAnalysis:
    input: str
    valid_format: bool
    local: str | None = None
    domain: str | None = None
    gravatar_url: str | None = None
    derived_usernames: list[str] = field(default_factory=list)
    # DNS — None means "not checked / unavailable", [] means "checked, none found"
    mx_records: list[str] | None = None
    has_mx: bool | None = None
    spf: str | None = None
    dmarc: str | None = None
    dns_checked: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "input": self.input,
            "valid_format": self.valid_format,
            "local": self.local,
            "domain": self.domain,
            "gravatar_url": self.gravatar_url,
            "derived_usernames": self.derived_usernames,
            "mx_records": self.mx_records,
            "has_mx": self.has_mx,
            "spf": self.spf,
            "dmarc": self.dmarc,
            "dns_checked": self.dns_checked,
            "notes": self.notes,
        }


def _derive_usernames(local: str) -> list[str]:
    out = {local}
    # split on separators
    parts = re.split(r"[._\-+]", local)
    out.update(p for p in parts if len(p) >= 2)
    # strip trailing digits (john123 -> john)
    stripped = re.sub(r"\d+$", "", local)
    if stripped and stripped != local and len(stripped) >= 2:
        out.add(stripped)
    return sorted(out)


def _gravatar_url(email: str) -> str:
    digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
    return f"https://www.gravatar.com/avatar/{digest}?d=404"


def analyze_email(email: str, *, dns_resolver: DnsResolver | None = None) -> EmailAnalysis:
    raw = (email or "").strip()
    m = _EMAIL_RE.match(raw)
    if not m:
        return EmailAnalysis(input=raw, valid_format=False, notes=["invalid_email_format"])

    local = m.group("local").lower()
    domain = m.group("domain").lower()
    result = EmailAnalysis(
        input=raw,
        valid_format=True,
        local=local,
        domain=domain,
        gravatar_url=_gravatar_url(raw),
        derived_usernames=_derive_usernames(local),
    )

    if dns_resolver is None:
        result.notes.append("dns_not_checked")
        return result

    result.dns_checked = True
    try:
        mx = dns_resolver(domain, "MX")
        result.mx_records = mx
        result.has_mx = len(mx) > 0
    except LookupError:
        result.mx_records = []
        result.has_mx = False

    try:
        txts = dns_resolver(domain, "TXT")
        spf = next((t for t in txts if t.lower().startswith("v=spf1")), None)
        result.spf = spf
    except LookupError:
        result.spf = None

    try:
        dmarc_txts = dns_resolver(f"_dmarc.{domain}", "TXT")
        dmarc = next((t for t in dmarc_txts if t.lower().startswith("v=dmarc1")), None)
        result.dmarc = dmarc
    except LookupError:
        result.dmarc = None

    return result


def default_dns_resolver(name: str, rtype: str) -> list[str]:
    """Real resolver backed by dnspython. Raises LookupError on failure."""
    import dns.resolver  # local import; keeps module import cheap/offline

    try:
        answers = dns.resolver.resolve(name, rtype, lifetime=5.0)
    except Exception as exc:  # NXDOMAIN, NoAnswer, Timeout, etc.
        raise LookupError(str(exc)) from exc
    out: list[str] = []
    for r in answers:
        if rtype == "MX":
            out.append(str(r.exchange).rstrip("."))
        elif rtype == "TXT":
            # join the chunked strings and strip quotes
            out.append(b"".join(r.strings).decode("utf-8", "replace"))
        else:
            out.append(str(r))
    return out
