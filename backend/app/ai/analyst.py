"""Investigation analyst — turns structured evidence into a grounded summary."""
from __future__ import annotations

from app.ai.router import AIMessage

SYSTEM_PROMPT = (
    "You are KAI's intelligence analyst. You work ONLY from the structured "
    "evidence provided. Rules you must never break:\n"
    "- Never claim two entities are the same person. Use 'observed', 'possible', "
    "'potential', 'one hypothesis is'.\n"
    "- Every claim must trace to a provided source URL or observation.\n"
    "- Distinguish observed facts from inferred relationships and from your own "
    "hypotheses.\n"
    "- If evidence is thin or conflicting, say so.\n"
    "Produce: (1) Summary, (2) Key observations (with sources), (3) Possible "
    "relationships (hedged), (4) Conflicts/gaps, (5) Recommended next research "
    "steps. Be concise and do not invent sources."
)


def build_context(
    investigation: dict,
    entities: list[dict],
    evidence: list[dict],
    relationships: list[dict],
) -> str:
    lines: list[str] = []
    lines.append(f"INVESTIGATION: {investigation.get('code')} — {investigation.get('name')}")
    if investigation.get("description"):
        lines.append(f"Description: {investigation['description']}")
    lines.append("\nENTITIES:")
    for e in entities:
        lines.append(f"- [{e['type']}] {e['value']}" + (f" ({e['label']})" if e.get("label") else ""))
    lines.append("\nEVIDENCE (observations with provenance):")
    for ev in evidence:
        band = f" band={ev['band']}" if ev.get("band") else ""
        conf = f" conf={ev['confidence']}" if ev.get("confidence") is not None else ""
        lines.append(f"- [{ev['type']}] source={ev['source_url']} collected={ev['collected_at']}{band}{conf}")
    lines.append("\nOBSERVED RELATIONSHIPS:")
    for r in relationships:
        lines.append(
            f"- {r['source_entity_id']} --{r['rel_type']}--> {r['target_entity_id']} "
            f"source={r['source_url']} observed={r['observed_at']}"
        )
    if not entities and not evidence:
        lines.append("\n(No entities or evidence collected yet.)")
    return "\n".join(lines)


def build_messages(context: str) -> list[AIMessage]:
    return [
        AIMessage(role="system", content=SYSTEM_PROMPT),
        AIMessage(role="user", content=f"Analyze this investigation evidence:\n\n{context}"),
    ]
