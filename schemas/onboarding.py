from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class CreateChurchRequest(BaseModel):
    church_name: str = Field(..., min_length=2, max_length=150)
    full_name: str = Field(..., min_length=2, max_length=150)


class CreateChurchResponse(BaseModel):
    church_id: UUID
    church_name: str
    user_id: UUID
    role: str
    created_at: datetime | None = None


class ChurchInfo(BaseModel):
    id: UUID
    name: str
    slug: str


class MeResponse(BaseModel):
    user_id: UUID
    email: str | None = None
    full_name: str | None = None
    role: str
    church: ChurchInfo