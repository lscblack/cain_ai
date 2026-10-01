"""Model registry — import all tables so SQLModel.metadata is complete."""
from app.database.models.audit import AuditLog
from app.database.models.user import User

__all__ = ["User", "AuditLog"]
