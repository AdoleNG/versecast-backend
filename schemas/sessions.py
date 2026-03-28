from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    # No fields needed — starting a session requires no input
    pass


class SessionResponse(BaseModel):
    id: UUID
    church_id: UUID
    started_at: datetime | None = None
    ended_at: datetime | None = None


class SessionHistoryItem(BaseModel):
    id: UUID
    church_id: UUID
    started_at: datetime | None = None
    ended_at: datetime | None = None
