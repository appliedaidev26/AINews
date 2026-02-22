"""Firebase ID token verification dependency for FastAPI routes."""
import logging
from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


async def get_current_uid(authorization: str = Header(...)) -> str:
    """
    Verify a Firebase ID token from the Authorization header.
    Returns the authenticated user's UID on success.
    Raises 401 on missing, malformed, or expired tokens.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must start with 'Bearer '",
        )

    token = authorization[len("Bearer "):]

    try:
        import firebase_admin.auth as fb_auth
        decoded = fb_auth.verify_id_token(token)
        return decoded["uid"]
    except ImportError:
        logger.error("firebase-admin not installed — run: pip install firebase-admin")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth service not available",
        )
    except Exception as exc:
        logger.warning(f"Token verification failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
