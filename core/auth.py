from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from core.supabase import get_admin_supabase

# Allow requests without Authorization header (so HTML pages can load)
security = HTTPBearer(auto_error=False)


def get_current_auth_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Extract and validate the Supabase user from the Authorization header.
    Returns the authenticated user object or raises HTTP 401.
    """

    # If no Authorization header was provided
    if credentials is None or credentials.credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = credentials.credentials
    supabase = get_admin_supabase()

    try:
        # Validate token with Supabase
        result = supabase.auth.get_user(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unable to verify user token: {str(e)}",
        )

    # Extract user object
    user = getattr(result, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user not found",
        )

    return user
