"""Model registry — import all tables so SQLModel.metadata is complete."""
from app.database.models.audit import AuditLog
from app.database.models.conversation import Conversation, Message
from app.database.models.entity import Entity
from app.database.models.evidence import Evidence
from app.database.models.face import Face
from app.database.models.investigation import Investigation
from app.database.models.relationship import Relationship
from app.database.models.security import (
    AuthorizedTarget,
    InstallRequest,
    SecurityFinding,
    ToolExecution,
    ToolVerification,
)
from app.database.models.source import Image, Page, Source
from app.database.models.user import User
from app.database.models.voice import (
    VoiceAsset,
    VoiceConversionSession,
    VoiceGeneration,
    VoiceModelRegistry,
    VoiceProfile,
)

__all__ = [
    "User",
    "AuditLog",
    "Investigation",
    "Entity",
    "Evidence",
    "Relationship",
    "Face",
    "Source",
    "Page",
    "Image",
    "Conversation",
    "Message",
    "ToolVerification",
    "ToolExecution",
    "InstallRequest",
    "AuthorizedTarget",
    "SecurityFinding",
    "VoiceProfile",
    "VoiceAsset",
    "VoiceGeneration",
    "VoiceConversionSession",
    "VoiceModelRegistry",
]
