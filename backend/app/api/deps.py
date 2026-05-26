from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.security import verify_supabase_jwt, extract_user_id

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    Dependency: extracts and validates the Bearer token from the request.
    Returns the full JWT payload including user_id (sub).
    Inject into any route that requires authentication.
    """
    
    token = credentials.credentials
    payload = verify_supabase_jwt(token)
    user_id = extract_user_id(payload)

    return {
        "user_id": user_id,
        "email": payload.get("email"),
        "payload": payload,
    }


async def get_current_user_id(
    current_user: dict = Depends(get_current_user),
) -> str:
    """Convenience dependency — returns just the user_id string."""
    return current_user["user_id"]
