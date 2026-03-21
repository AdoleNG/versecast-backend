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


@router.post("/create-church", response_model=CreateChurchResponse)
def create_church(
    payload: CreateChurchRequest,
    auth_user=Depends(get_current_auth_user),
):
    supabase = get_admin_supabase()

    auth_user_id = auth_user.id
    auth_email = getattr(auth_user, "email", None)

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

    church_name = payload.church_name.strip()
    church_slug = church_name.lower().replace(" ", "-")

    church_res = (
        supabase.table("churches")
        .insert(
            {
                "name": church_name,
                "slug": church_slug,
            }
        )
        .execute()
    )

    church_rows = church_res.data or []
    if not church_rows:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create church",
        )

    church = church_rows[0]
    church_id = church["id"]

    try:
        user_res = (
            supabase.table("users")
            .insert(
                {
                    "id": auth_user_id,
                    "church_id": church_id,
                    "full_name": payload.full_name.strip(),
                    "email": auth_email,
                    "role": "owner",
                    "status": "active",
                }
            )
            .execute()
        )

        user_rows = user_res.data or []
        if not user_rows:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create owner profile",
            )

        supabase.table("church_settings").insert(
            {
                "church_id": church_id,
                "display_mode": "assist",
                "approval_required": True,
                "hold_seconds": 10,
                "default_translation": "KJV",
                "max_range_verses": 10,
            }
        ).execute()

        return CreateChurchResponse(
            church_id=church["id"],
            church_name=church["name"],
            user_id=user_rows[0]["id"],
            role=user_rows[0]["role"],
            created_at=church.get("created_at"),
        )

    except Exception as e:
        try:
            supabase.table("users").delete().eq("id", auth_user_id).execute()
        except Exception:
            pass

        try:
            supabase.table("church_settings").delete().eq("church_id", church_id).execute()
        except Exception:
            pass

        try:
            supabase.table("churches").delete().eq("id", church_id).execute()
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Onboarding failed: {str(e)}",
        )


@router.get("/me", response_model=MeResponse)
def get_me(auth_user=Depends(get_current_auth_user)):
    supabase = get_admin_supabase()

    auth_user_id = auth_user.id
    auth_email = getattr(auth_user, "email", None)

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

    church_res = (
        supabase.table("churches")
        .select("id, name, slug")
        .eq("id", church_id)
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
            id=church["id"],
            name=church["name"],
            slug=church["slug"],
        ),
    )