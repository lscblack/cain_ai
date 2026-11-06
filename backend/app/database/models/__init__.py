"""Model registry — import all tables so SQLModel.metadata is complete."""
from app.database.models.audit import AuditLog
from app.database.models.conversation import Conversation, Message
from app.database.models.entity import Entity
from app.database.models.enrich import (
    ExternalEndpoint,
    Parcel,
    ParcelOwnership,
    Person,
    PhoneNumber,
    ScrapeJob,
)
from app.database.models.evidence import Evidence
from app.database.models.face import Face
from app.database.models.investigation import Investigation
from app.database.models.relationship import Relationship
from app.database.models.security import (
    AuthorizedTarget,
    CustomCapability,
    InstallRequest,
    KaiCapabilities,
    KaiFile,
    KaiProfile,
    KaiSkill,
    SecurityFinding,
    ToolDoc,
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
# NOTE: app.ingestion models removed — the subsystem source was lost (never
# committed) and is being rebuilt. Re-add these imports when it returns.

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
    "ToolDoc",
    "KaiCapabilities",
    "KaiFile",
    "KaiProfile",
    "KaiSkill",
    "CustomCapability",
    "ExternalEndpoint",
    "Person",
    "Parcel",
    "ParcelOwnership",
    "PhoneNumber",
    "ScrapeJob",
    "VoiceProfile",
    "VoiceAsset",
    "VoiceGeneration",
    "VoiceConversionSession",
    "VoiceModelRegistry",
]
