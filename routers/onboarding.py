from fastapi import APIRouter, Depends, HTTPException, status
from schemas.onboarding import (
    CreateChurchRequest,
    CreateChurchResponse,
    MeResponse,
    ChurchInfo,
)
from core.auth import get_current_auth_user
from core.supabase import get_admin_supabase

router = APIRouter(
    prefix="/saas/onboarding",
    tags=["onboarding"],
)

# =========================================================
# CREATE CHURCH (OWNER ONBOARDING)
# =========================================================
@router.post("/create-church", response_model=CreateChurchResponse)
def create_church(
    payload: CreateChurchRequest,
    auth_user=Depends(get_current_auth_user),
):
    supabase = get_admin_supabase()

    auth_user_id = auth_user.id
    auth_email = getattr(auth_user, "email", None)

    # Check if user already exists in public.users
    existing_user_res = (
        supabase.table("users")
        .select("id, church_id, role")
        .eq("id", auth_user_id)
        .limit(1)
        .execute()
    )

    existing_users = existing_user_res.data or []
    if existing_users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User has already completed church onboarding",
        )

    # Prepare church data
    church_name = payload.church_name.strip()
    church_slug = church_name.lower().replace(" ", "-")

    # Create church (sync client does NOT support .select() after insert)
church_insert_res = (
    supabase.table("churches")
    .insert(
        {
            "name": church_name,
            "slug": church_slug,
            "created_by": auth_user_id,
        }
    )
    .execute()
)

if church_insert_res.error or not church_insert_res.data:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to create church",
    )

# Fetch the inserted church row
church_res = (
    supabase.table("churches")
    .select("church_id, name, slug, created_at")
    .eq("slug", church_slug)
    .single()
    .execute()
)

if church_res.error or not church_res.data:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to fetch created church",
    )

church = church_res.data
church_id = church["church_id"]

    if church_res.error or not church_res.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create church",
        )

    church = church_res.data
    church_id = church["church_id"]

    try:
        # Create owner user profile
        user_insert_res = (
    supabase.table("users")
    .insert({...})
    .execute()
)

if user_insert_res.error or not user_insert_res.data:
    raise Exception("Failed to create owner profile")

user_res = (
    supabase.table("users")
    .select("id, role")
    .eq("id", auth_user_id)
    .single()
    .execute()
)

if user_res.error or not user_res.data:
    raise Exception("Failed to fetch owner profile")

user = user_res.data

        )

        if user_res.error or not user_res.data:
            raise Exception("Failed to create owner profile")

        user = user_res.data

        # Create default church settings
        settings_res = (
            supabase.table("church_settings")
            .insert(
                {
                    "church_id": church_id,
                    "display_mode": "assist",
                    "approval_required": True,
                    "hold_seconds": 10,
                    "default_translation": "KJV",
                    "max_range_verses": 15,
                }
            )
            .execute()
        )

        if settings_res.error:
            raise Exception("Failed to create church settings")

        return CreateChurchResponse(
            church_id=church_id,
            church_name=church["name"],
            user_id=user["id"],
            role=user["role"],
            created_at=church.get("created_at"),
        )

    except Exception as e:
        # Cleanup on failure
        try:
            supabase.table("users").delete().eq("id", auth_user_id).execute()
        except Exception:
            pass

        try:
            supabase.table("church_settings").delete().eq("church_id", church_id).execute()
        except Exception:
            pass

        try:
            supabase.table("churches").delete().eq("church_id", church_id).execute()
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Onboarding failed: {str(e)}",
        )


# =========================================================
# GET CURRENT USER + CHURCH
# =========================================================
@router.get("/me", response_model=MeResponse)
def get_me(auth_user=Depends(get_current_auth_user)):
    supabase = get_admin_supabase()

    auth_user_id = auth_user.id
    auth_email = getattr(auth_user, "email", None)

    # Load user profile
    user_res = (
        supabase.table("users")
        .select("id, full_name, role, church_id")
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

    # Load church info
    church_res = (
        supabase.table("churches")
        .select("church_id, name, slug")
        .eq("church_id", church_id)
        .limit(1)
        .execute()
    )

    church_rows = church_res.data or []
    if not church_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Church not found for this user.",
        )

    church = church_rows[0]

    return MeResponse(
        user_id=user["id"],
        email=auth_email,
        full_name=user.get("full_name"),
        role=user["role"],
        church=ChurchInfo(
            id=church["church_id"],
            name=church["name"],
            slug=church["slug"],
        ),
    )
