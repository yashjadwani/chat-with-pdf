import jwt
from fastapi import HTTPException, status
from app.core.config import get_settings
from functools import lru_cache
from jwt import PyJWKClient

settings = get_settings()

def get_supabase_jwks_url() -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

@lru_cache()
def get_jwks_client() -> PyJWKClient:
    return PyJWKClient(get_supabase_jwks_url())

def verify_supabase_jwt(token: str) -> dict:
    """
    Verify a Supabase-issued JWT and return the decoded payload.
    Raises HTTPException if token is invalid or expired.
    """
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_user_id(payload: dict) -> str:
    """Extract user_id (sub) from decoded JWT payload."""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity",
        )
    return user_id
