from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr


class InviteOperatorRequest(BaseModel):
    email: EmailStr


class OperatorInvitationResponse(BaseModel):
    id: UUID
    church_id: UUID
    email: EmailStr
    role: str
    status: str
    invitation_token: UUID
    expires_at: datetime | None = None
    created_at: datetime | None = None


class OperatorUserItem(BaseModel):
    id: UUID
    full_name: str | None = None
    email: EmailStr | None = None
    role: str
    status: str | None = None
    created_at: datetime | None = None

class PendingInvitationItem(BaseModel):
    id: UUID
    email: EmailStr
    role: str
    status: str
    invitation_token: UUID
    expires_at: datetime | None = None
    created_at: datetime | None = None
    invited_by: UUID


class OperatorsListResponse(BaseModel):
    church_id: UUID
    operators: list[OperatorUserItem]
    pending_invitations: list[PendingInvitationItem]

class InvitationLookupResponse(BaseModel):
    id: UUID
    church_id: UUID
    church_name: str
    email: EmailStr
    role: str
    status: str
    expires_at: datetime | None = None
    created_at: datetime | None = None


class AcceptInvitationRequest(BaseModel):
    token: UUID
    full_name: str


class AcceptInvitationResponse(BaseModel):
    message: str
    login_url: str


class OperatorStatusResponse(BaseModel):
    id: UUID
    church_id: UUID
    email: EmailStr | None = None
    full_name: str | None = None
    role: str
    status: str