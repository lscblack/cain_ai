"""Model registry — import all tables so SQLModel.metadata is complete."""
from app.database.models.audit import AuditLog
from app.database.models.entity import Entity
from app.database.models.evidence import Evidence
from app.database.models.face import Face
from app.database.models.investigation import Investigation
from app.database.models.relationship import Relationship
from app.database.models.source import Image, Page, Source
from app.database.models.user import User

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
]
