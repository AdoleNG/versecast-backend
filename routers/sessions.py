from fastapi import APIRouter, Depends, HTTPException, status
from core.auth import get_current_auth_user
from core.supabase import get_admin_supabase
from schemas.sessions import StartSessionRequest, SessionResponse, SessionHistoryItem
from datetime import datetime, timezone

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
)


@router.post("/start", response_model=SessionResponse)
def start_session(
    payload: StartSessionRequest,
    auth_user=Depends(get_current_auth_user),
):
    supabase = get_admin_supabase()
    auth_user_id = auth_user.id

    # Load user profile
    user_res = (
        supabase.table("users")
        .select("id, church_id, role")
        .eq("id", auth_user_id)
        .limit(1)
        .execute()
    )

    user_rows = user_res.data or []
    if not user_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found. Onboarding may not be completed.",
        )

    user = user_rows[0]
    church_id = user["church_id"]

    # Ensure there is no active session for this church
    active_res = (
        supabase.table("service_sessions")
        .select("id")
        .eq("church_id", church_id)
        .is_("ended_at", None)
        .limit(1)
        .execute()
    )

    active_rows = active_res.data or []
    if active_rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This church already has an active session.",
        )

    # Create new session
    session_res = (
        supabase.table("service_sessions")
        .insert({
            "church_id": church_id,
            "title": payload.title.strip(),
            "created_by": auth_user_id,
        })
        .execute()
    )

    session_rows = session_res.data or []
    if not session_rows:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create session.",
        )

    session = session_rows[0]

    return SessionResponse(
        id=session["id"],
        church_id=session["church_id"],
        title=session["title"],
        started_at=session.get("started_at"),
        ended_at=session.get("ended_at"),
    )

@router.get("/current", response_model=SessionResponse)
def get_current_session(auth_user=Depends(get_current_auth_user)):
    supabase = get_admin_supabase()
    auth_user_id = auth_user.id

    # Load user profile
    user_res = (
        supabase.table("users")
        .select("id, church_id")
        .eq("id", auth_user_id)
        .limit(1)
        .execute()
    )

    user_rows = user_res.data or []
    if not user_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found. Onboarding may not be completed.",
        )

    church_id = user_rows[0]["church_id"]

    # Find active session = session with no ended_at
    session_res = (
        supabase.table("service_sessions")
        .select("id, church_id, title, started_at, ended_at")
        .eq("church_id", church_id)
        .is_("ended_at", None)
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )

    session_rows = session_res.data or []
    if not session_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session found for this church.",
        )

    session = session_rows[0]

    return SessionResponse(
        id=session["id"],
        church_id=session["church_id"],
        title=session["title"],
        started_at=session.get("started_at"),
        ended_at=session.get("ended_at"),
    )
@router.post("/end", response_model=SessionResponse)
def end_session(auth_user=Depends(get_current_auth_user)):
    supabase = get_admin_supabase()
    auth_user_id = auth_user.id

    # Load user profile
    user_res = (
        supabase.table("users")
        .select("id, church_id")
        .eq("id", auth_user_id)
        .limit(1)
        .execute()
    )

    user_rows = user_res.data or []
    if not user_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found. Onboarding may not be completed.",
        )

    church_id = user_rows[0]["church_id"]

    # Find active session = session with no ended_at
    session_res = (
        supabase.table("service_sessions")
        .select("id, church_id, title, started_at, ended_at")
        .eq("church_id", church_id)
        .is_("ended_at", None)
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )

    session_rows = session_res.data or []
    if not session_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session found for this church.",
        )

    session = session_rows[0]
    session_id = session["id"]

    # End the session
    update_res = (
        supabase.table("service_sessions")
        .update({
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "ended_by": auth_user_id,
        })
        .eq("id", session_id)
        .execute()
    )

    updated_rows = update_res.data or []
    if not updated_rows:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to end session.",
        )

    updated = updated_rows[0]

    return SessionResponse(
        id=updated["id"],
        church_id=updated["church_id"],
        title=updated["title"],
        started_at=updated.get("started_at"),
        ended_at=updated.get("ended_at"),
    )
@router.get("/history", response_model=list[SessionHistoryItem])
def get_session_history(auth_user=Depends(get_current_auth_user)):
    supabase = get_admin_supabase()
    auth_user_id = auth_user.id

    # Load user profile
    user_res = (
        supabase.table("users")
        .select("church_id")
        .eq("id", auth_user_id)
        .limit(1)
        .execute()
    )

    user_rows = user_res.data or []
    if not user_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found. Onboarding may not be completed.",
        )

    church_id = user_rows[0]["church_id"]

    # Get recent sessions for this church
    session_res = (
        supabase.table("service_sessions")
        .select("id, church_id, title, started_at, ended_at")
        .eq("church_id", church_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )

    rows = session_res.data or []

    return [
        SessionHistoryItem(
            id=row["id"],
            church_id=row["church_id"],
            title=row["title"],
            started_at=row.get("started_at"),
            ended_at=row.get("ended_at"),
        )
        for row in rows
    ]
