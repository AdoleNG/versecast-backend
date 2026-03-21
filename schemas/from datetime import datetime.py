from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    title: str
    session_type: str = "service"


class SessionResponse(BaseModel):
    id: UUID
    church_id: UUID
    title: str
    session_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None