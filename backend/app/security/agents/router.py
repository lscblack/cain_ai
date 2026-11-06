"""Route a chat message to one agent: rules first, model second."""
from __future__ import annotations

import re
from typing import Awaitable, Callable, Literal, TypedDict

from app.ai.router import AIMessage
from app.security.agents.profiles import AGENT_IDS, PROFILES


class RouteResult(TypedDict):
    agent: str
    reason: Literal["rule", "model", "manual", "fallback"]
    confidence: float


_SHELL_CMD = re.compile(r"\b(curl|nmap|dig|whois|nc|ssh)\b", re.I)
_SHELL_SHAPE = re.compile(r"^\s*\$\s*\S|\s\|\s\S")
_URL = re.compile(r"https?://\S+", re.I)
_DOMAIN = re.compile(
    r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|net|org|io|rw|dev|info|gov|edu|co)\b", re.I
)
_NID = re.compile(r"\b\d{16}\b")
_PHONE = re.compile(r"(?<!\d)(\+?\d{1,3}[\s-]?)?\(?0?7\d{2}\)?[\s-]?\d{3}[\s-]?\d{3}(?!\d)")
_MAP = re.compile(r"\b(route|directions|navigate|map|place|near me)\b", re.I)
_WEB = re.compile(r"\b(search|news|latest|find out|look up online)\b", re.I)
_INV = re.compile(
    r"\b(investigation|evidence|save (this )?as|write (a )?(file|report))\b", re.I
)

_THRESHOLD = 0.6
_MARGIN = 0.2


def score_rules(message: str) -> dict[str, float]:
    s = {a: 0.0 for a in AGENT_IDS}
    if _SHELL_CMD.search(message) or _SHELL_SHAPE.search(message):
        s["shell_network"] = 0.8
    if _URL.search(message):
        s["shell_network"] = min(1.0, s["shell_network"] + 0.1) if s["shell_network"] else 0.4
    elif _DOMAIN.search(message):
        s["shell_network"] = max(s["shell_network"], 0.4)
    if _NID.search(message):
        s["people_identity"] = 0.9
    elif _PHONE.search(message):
        s["people_identity"] = 0.7
    if _MAP.search(message):
        s["map_geo"] = 0.8
    if _WEB.search(message):
        s["web_research"] = 0.8
    if _INV.search(message):
        s["investigations_files"] = 0.8
    if not any(s.values()):
        s["general"] = 0.3  # unmatched text: weak general hit
    return s


async def _default_model_classify(message: str) -> str | None:
    """One short provider call; returns an agent id or None. Import-safe and lazy."""
    try:
        from app.ai.router import get_ai_provider

        provider = get_ai_provider()
        if provider is None:
            return None
        prompt = (
            "Classify the user's message to exactly one agent. Reply with only one of: "
            + ", ".join(AGENT_IDS)
            + ".\nshell_network: commands, DNS, ports, TLS, domains. web_research: web "
            "search/news. map_geo: places/routes. people_identity: national ID/phone "
            "lookups. investigations_files: investigations, evidence, files. general: "
            "everything else."
        )
        reply = await provider.chat(
            [AIMessage(role="system", content=prompt),
             AIMessage(role="user", content=message[:2000])],
            temperature=0.0,
        )
        cleaned = (reply or "").strip().strip("`'\".").lower()
        return cleaned if cleaned in AGENT_IDS else None
    except Exception:
        return None


async def route(
    message: str,
    history: list[AIMessage] | None = None,
    forced: str | None = None,
    model_classify: Callable[[str], Awaitable[str | None]] | None = None,
) -> RouteResult:
    if forced and forced in PROFILES:
        return {"agent": forced, "reason": "manual", "confidence": 1.0}

    scores = score_rules(message)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, top_score = ranked[0]
    runner = ranked[1][1]
    if top == "general":
        return {"agent": "general", "reason": "rule", "confidence": top_score}
    if top_score >= _THRESHOLD and top_score - runner >= _MARGIN:
        return {"agent": top, "reason": "rule", "confidence": top_score}

    classify = model_classify or _default_model_classify
    try:
        picked = await classify(message)
    except Exception:
        picked = None
    if picked in AGENT_IDS:
        return {"agent": picked, "reason": "model", "confidence": 0.5}
    return {"agent": "general", "reason": "fallback", "confidence": 0.0}
