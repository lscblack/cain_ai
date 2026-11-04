"""Core types for the person-investigation agents."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import Person


@dataclass(frozen=True)
class Fact:
    id: str
    claim: str
    value: str
    source: Literal["db", "web", "inference"]
    source_ref: str
    retrieved_at: str
    confidence: int  # 0-100

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 100:
            raise ValueError(f"confidence must be 0-100, got {self.confidence}")


@dataclass
class Request:
    nid: str | None = None
    phone: str | None = None
    name: str | None = None
    image: bytes | None = None
    web: bool = False
    analyse: bool = False


@dataclass
class AgentResult:
    agent: str
    ok: bool
    facts: list[Fact] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Ctx:
    session: AsyncSession
    user_id: uuid.UUID
    request: Request
    person: Person | None
    results: dict[str, AgentResult]
    emit: Callable[[str, dict], Awaitable[None]]


class Agent(Protocol):
    name: str

    def can_handle(self, ctx: Ctx) -> bool: ...

    async def run(self, ctx: Ctx) -> AgentResult: ...


def new_fact_id(n: int) -> str:
    return f"F{n}"
