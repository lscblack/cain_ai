"""Agent profiles: a prompt plus a narrow allowed-toolset each."""
from __future__ import annotations

from dataclasses import dataclass

from app.security.capabilities import SHELL_OP_KEY
from app.security.service import DATA_LOOKUP_OP_KEY, IDENTITY_LOOKUP_OP_KEY
from app.security.web import MAPS_FIND_OP_KEY, WEB_OPEN_OP_KEY, WEB_SEARCH_OP_KEY
from app.security.workspace import LIST_OP_KEY, WRITE_OP_KEY


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    system_prompt: str
    allowed_tools: frozenset[str]
    max_steps: int


AGENT_IDS: tuple[str, ...] = (
    "shell_network",
    "web_research",
    "map_geo",
    "people_identity",
    "investigations_files",
    "general",
)

_PROFILE_LIST = [
    AgentProfile(
        id="shell_network",
        name="Shell & Network",
        system_prompt=(
            "You run shell commands and network diagnostics (DNS, WHOIS, HTTP headers, "
            "TLS, port scans, SSH auth logs, firewall status, CVE lookups) against "
            "targets the user is authorised to examine. Report only what the command's "
            "actual output shows. If a command fails, times out, or returns nothing, "
            "say so explicitly — never infer or guess a result."
        ),
        allowed_tools=frozenset({
            SHELL_OP_KEY, "dns.records", "whois.lookup", "http.headers", "tls.inspect",
            "nmap.service_scan", "logs.ssh_auth", "firewall.status", "cve.lookup",
        }),
        max_steps=8,
    ),
    AgentProfile(
        id="web_research",
        name="Web Research",
        system_prompt=(
            "You research public information on the web: search for current news and "
            "facts, open specific URLs, and summarise what the pages actually say with "
            "their sources. Do not state anything the retrieved pages do not support."
        ),
        allowed_tools=frozenset({WEB_SEARCH_OP_KEY, WEB_OPEN_OP_KEY}),
        max_steps=5,
    ),
    AgentProfile(
        id="map_geo",
        name="Maps & Geo",
        system_prompt=(
            "You answer geographic questions: finding places, routes, directions and "
            "nearby locations using the map lookup tool. Report only places and "
            "distances the tool returned."
        ),
        allowed_tools=frozenset({MAPS_FIND_OP_KEY}),
        max_steps=5,
    ),
    AgentProfile(
        id="people_identity",
        name="People & Identity",
        system_prompt=(
            "You look up people and identities from the platform's data sources: "
            "national ID and phone lookups, data lookups and people investigations. "
            "Report only the records returned and say clearly when nothing was found."
        ),
        allowed_tools=frozenset({IDENTITY_LOOKUP_OP_KEY, DATA_LOOKUP_OP_KEY, "people.investigate"}),
        max_steps=5,
    ),
    AgentProfile(
        id="investigations_files",
        name="Investigations & Files",
        system_prompt=(
            "You manage investigations (create, list, inspect, add entities and "
            "evidence, delete) and the user's workspace files (list and write reports "
            "or notes). Confirm exactly what was created or changed."
        ),
        allowed_tools=frozenset({
            WRITE_OP_KEY, LIST_OP_KEY,
            "investigation.create", "investigation.list", "investigation.get",
            "investigation.add_entity", "investigation.add_evidence",
            "investigation.delete",
        }),
        max_steps=8,
    ),
    AgentProfile(
        id="general",
        name="General",
        system_prompt=(
            "You are a general assistant for conversation, explanation and "
            "questions that need no tools. You have no tools available; do not claim "
            "to have run anything."
        ),
        allowed_tools=frozenset(),
        max_steps=3,
    ),
]

PROFILES: dict[str, AgentProfile] = {p.id: p for p in _PROFILE_LIST}
assert tuple(PROFILES) == AGENT_IDS
