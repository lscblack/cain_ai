"""Chat conversations and messages for the local KAI model."""
from __future__ import annotations

import uuid

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class Conversation(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "conversations"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    title: str = Field(default="New conversation")
    model: str = Field(default="kai-security")
    archived: bool = Field(default=False, index=True)


class Message(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "messages"

    conversation_id: uuid.UUID = Field(index=True, nullable=False, foreign_key="conversations.id")
    role: str = Field(nullable=False)  # user | assistant | system | tool
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    # Tool requests the model emitted (validated JSON) and their structured results.
    tool_calls: list | None = Field(default=None, sa_column=Column(JSONB))
    tool_results: list | None = Field(default=None, sa_column=Column(JSONB))
    meta: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}"))
