from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from supabase_auth.errors import AuthApiError

from core.auth import get_current_auth_user
from core.email import send_operator_invitation_email
from core.supabase import get_admin_supabase

from schemas.operators import (
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    InvitationLookupResponse,
    InviteOperatorRequest,
    OperatorInvitationResponse,
    OperatorsListResponse,
    OperatorStatusResponse,
    OperatorUserItem,
    PendingInvitationItem,
)

router = APIRouter(prefix="/operators", tags=["operators"])


# =========================================================
# HELPERS
# =========================================================

def get_user_church_id(user_id: str):
    supabase = get_admin_supabase()
    res = (
        supabase.table("users")
        .select("church_id")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0]["church_id"] if rows else None

# =========================================================
# INVITE OPERATOR
# =========================================================

@router.post("/invite", response_model=OperatorInvitationResponse)
def invite_operator(
    payload: InviteOperatorRequest,
    auth_user=Depends(get_current_auth_user),
):
    print("ROUTER: about to call send_operator_invitation_email")
    supabase = get_admin_supabase()
    auth_user_id = auth_user.id

    # 1. Fetch inviter profile
    user_res = (
        supabase.table("users")
        .select("id, church_id, role, email")
        .eq("id", auth_user_id)
        .limit(1)
        .execute()
    )

    inviter = (user_res.data or [None])[0]
    if not inviter:
        raise HTTPException(404, "User profile not found")

    if inviter["role"] != "owner":
        raise HTTPException(403, "Only the church owner can invite operators")

    church_id = inviter["church_id"]
    invited_email = payload.email.strip().lower()
    inviter_email = (inviter["email"] or "").strip().lower()

    if invited_email == inviter_email:
        raise HTTPException(400, "You cannot invite yourself")

    # 2. Check if user already exists in this church
    existing_user = (
        supabase.table("users")
        .select("id")
        .eq("church_id", church_id)
        .ilike("email", invited_email)
        .limit(1)
        .execute()
    )

    if existing_user.data:
        raise HTTPException(409, "A user with this email already belongs to your church")

    # 3. Check for existing pending invitation
    existing_invite = (
        supabase.table("operator_invitations")
        .select("id")
        .eq("church_id", church_id)
        .eq("status", "pending")
        .ilike("email", invited_email)
        .limit(1)
        .execute()
    )

    if existing_invite.data:
        raise HTTPException(409, "A pending invitation already exists for this email")

    # 4. Create invitation
    token = str(uuid4())
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

    invite_res = (
        supabase.table("operator_invitations")
        .insert({
            "church_id": church_id,
            "invited_by": auth_user_id,
            "email": invited_email,
            "role": "operator",
            "status": "pending",
            "invitation_token": token,
            "expires_at": expires_at,
        })
        .execute()
    )

    invite = (invite_res.data or [None])[0]
    if not invite:
        raise HTTPException(500, "Failed to create operator invitation")

    # 5. Fetch church name
    church_res = (
        supabase.table("churches")
        .select("name")
        .eq("church_id", church_id)
        .limit(1)
        .execute()
    )

    church = (church_res.data or [None])[0]
    if not church:
        raise HTTPException(404, "Church not found")

    # 6. Send email
    try:
        send_operator_invitation_email(
            to_email=invited_email,
            church_name=church["name"],
            invitation_token=token,
        )
    except Exception as e:
        raise HTTPException(
            500,
            f"Invitation created, but email failed to send: {str(e)}",
        )

    return OperatorInvitationResponse(
        id=invite["id"],
        church_id=invite["church_id"],
        email=invite["email"],
        role=invite["role"],
        status=invite["status"],
        invitation_token=invite["invitation_token"],
        expires_at=invite.get("expires_at"),
        created_at=invite.get("created_at"),
    )


# =========================================================
# LIST OPERATORS + PENDING INVITES
# =========================================================

@router.get("", response_model=OperatorsListResponse)
def list_operators(auth_user=Depends(get_current_auth_user)):
    supabase = get_admin_supabase()

    # Fetch user
    user_res = (
        supabase.table("users")
        .select("church_id, role")
        .eq("id", auth_user.id)
        .limit(1)
        .execute()
    )

    user = (user_res.data or [None])[0]
    if not user:
        raise HTTPException(404, "User not found")

    if user["role"] != "owner":
        raise HTTPException(403, "Only owner can view operators")

    church_id = user["church_id"]

    # Fetch operators
    operators_res = (
        supabase.table("users")
        .select("id, full_name, email, role, status, created_at")
        .eq("church_id", church_id)
        .eq("role", "operator")
        .order("created_at", desc=True)
        .execute()
    )

    # Fetch pending invitations
    invites_res = (
        supabase.table("operator_invitations")
        .select("id, email, role, status, invitation_token, expires_at, created_at, invited_by")
        .eq("church_id", church_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )

    return OperatorsListResponse(
        church_id=church_id,
        operators=[OperatorUserItem(**row) for row in (operators_res.data or [])],
        pending_invitations=[PendingInvitationItem(**row) for row in (invites_res.data or [])],
    )


# =========================================================
# INVITATION LOOKUP
# =========================================================

@router.get("/invitations/{token}", response_model=InvitationLookupResponse)
def get_invitation_details(token: UUID):
    supabase = get_admin_supabase()

    invite_res = (
        supabase.table("operator_invitations")
        .select("*")
        .eq("invitation_token", str(token))
        .limit(1)
        .execute()
    )

    invite = (invite_res.data or [None])[0]
    if not invite:
        raise HTTPException(404, "Invitation not found")

    if invite["status"] != "pending":
        raise HTTPException(400, f"Invitation is not pending. Status: {invite['status']}")

    # Check expiration
    expires_at = invite.get("expires_at")
    if expires_at:
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires_dt <= datetime.now(timezone.utc):
            raise HTTPException(400, "Invitation has expired")

    # Fetch church
    church_res = (
        supabase.table("churches")
        .select("name")
        .eq("church_id", invite["church_id"])
        .limit(1)
        .execute()
    )

    church = (church_res.data or [None])[0]
    if not church:
        raise HTTPException(404, "Church not found")

    return InvitationLookupResponse(
        id=invite["id"],
        church_id=invite["church_id"],
        church_name=church["name"],
        email=invite["email"],
        role=invite["role"],
        status=invite["status"],
        expires_at=invite.get("expires_at"),
        created_at=invite.get("created_at"),
    )


import os
from datetime import datetime, timezone
from fastapi import HTTPException

# =========================================================
# ACCEPT INVITATION
# =========================================================

@router.post("/accept-invite", response_model=AcceptInvitationResponse)
def accept_invitation(payload: AcceptInvitationRequest):
    supabase = get_admin_supabase()

    token = str(payload.token)
    full_name = payload.full_name.strip()

    if not full_name:
        raise HTTPException(400, "Full name is required")

    frontend_base_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

    # 1. Lookup invitation
    invite_res = (
        supabase.table("operator_invitations")
        .select("*")
        .eq("invitation_token", token)
        .limit(1)
        .execute()
    )

    invite = (invite_res.data or [None])[0]
    if not invite:
        raise HTTPException(404, "Invitation not found")

    if invite["status"] != "pending":
        raise HTTPException(400, "Invitation already used")

    invited_email = invite["email"]

    # 2. Create or fetch user
    try:
        created = supabase.auth.admin.create_user({
            "email": invited_email,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name},
        })
        user_id = created.user.id

    except AuthApiError as e:
        if "already been registered" in str(e):
            all_users = supabase.auth.admin.list_users()
            match = [u for u in all_users if u.email.lower() == invited_email.lower()]
            if not match:
                raise HTTPException(500, "User exists but cannot be retrieved")
            user_id = match[0].id
        else:
            raise

    # 3. Generate magic link that returns user to dashboard
    redirect_to = f"{frontend_base_url}/dashboard"

    magic = supabase.auth.admin.generate_link({
        "type": "magiclink",
        "email": invited_email,
        "options": {
            "redirect_to": redirect_to
        },
    })

    login_url = magic.properties.action_link

    # 4. Mark invitation accepted
    supabase.table("operator_invitations").update({
        "status": "accepted",
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
    }).eq("id", invite["id"]).execute()
    # ⭐ ADD THIS BLOCK
    supabase.table("users").upsert({
        "id": user_id,
        "full_name": full_name,
        "email": invited_email,
        "church_id": invite["church_id"],
        "role": "operator",
        "status": "active",
    }).execute()
    return AcceptInvitationResponse(
        message=f"Invitation accepted successfully. Welcome, {full_name}!",
        login_url=login_url,
    )


# =========================================================
# DEACTIVATE OPERATOR
# =========================================================

@router.post("/{operator_id}/deactivate", response_model=OperatorStatusResponse)
def deactivate_operator(operator_id: str, auth_user=Depends(get_current_auth_user)):
    supabase = get_admin_supabase()

    # Fetch owner
    owner_res = (
        supabase.table("users")
        .select("id, church_id, role")
        .eq("id", auth_user.id)
        .limit(1)
        .execute()
    )

    owner = (owner_res.data or [None])[0]
    if not owner:
        raise HTTPException(404, "User profile not found")

    if owner["role"] != "owner":
        raise HTTPException(403, "Only the church owner can deactivate operators")

    church_id = owner["church_id"]

    # Fetch operator
    target_res = (
        supabase.table("users")
        .select("id, church_id, email, full_name, role, status")
        .eq("id", operator_id)
        .limit(1)
        .execute()
    )

    target = (target_res.data or [None])[0]
    if not target:
        raise HTTPException(404, "Operator not found")

    if target["church_id"] != church_id:
        raise HTTPException(403, "You can only deactivate operators in your own church")

    if target["role"] != "operator":
        raise HTTPException(400, "Only operator accounts can be deactivated")

    if target.get("status") == "inactive":
        raise HTTPException(409, "Operator is already inactive")

    # Deactivate
    update_res = (
        supabase.table("users")
        .update({"status": "inactive"})
        .eq("id", operator_id)
        .eq("church_id", church_id)
        .eq("role", "operator")
        .execute()
    )

    updated = (update_res.data or [None])[0]
    if not updated:
        raise HTTPException(500, "Failed to deactivate operator")

    return OperatorStatusResponse(
        id=updated["id"],
        church_id=updated["church_id"],
        email=updated.get("email"),
        full_name=updated.get("full_name"),
        role=updated["role"],
        status=updated["status"],
    )
