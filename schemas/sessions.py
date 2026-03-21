from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    title: str


class SessionResponse(BaseModel):
    id: UUID
    church_id: UUID
    title: str
    started_at: datetime | None = None
    ended_at: datetime | None = None


class SessionHistoryItem(BaseModel):
    id: UUID
    church_id: UUID
    title: str
    started_at: datetime | None = None
    ended_at: datetime | None = None