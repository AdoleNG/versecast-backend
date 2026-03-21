from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from core.supabase import get_admin_supabase

security = HTTPBearer()


def get_current_auth_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    supabase = get_admin_supabase()

    try:
        result = supabase.auth.get_user(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unable to verify user token: {str(e)}",
        )

    user = getattr(result, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user not found",
        )

    return user