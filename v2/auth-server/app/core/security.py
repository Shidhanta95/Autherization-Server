"""
Security utilities for JWT handling and authentication dependencies.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from app.core.config import settings

# HTTP Bearer scheme for extracting tokens from Authorization header
security = HTTPBearer()


class TokenData:
    """Data extracted from a validated JWT token"""

    def __init__(
        self,
        email: str,
        user_id: str,
        organization: str,
        platform: str,
        is_org_admin: int,
        permissions: dict,
        exp: datetime,
    ):
        self.email = email
        self.user_id = user_id
        self.organization = organization
        self.platform = platform
        self.is_org_admin = is_org_admin
        self.permissions = permissions
        self.exp = exp


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token string

    Returns:
        The decoded token claims

    Raises:
        HTTPException: If the token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def validate_token_expiry(payload: dict) -> None:
    """
    Validate that the token has not expired.

    Args:
        payload: The decoded token payload

    Raises:
        HTTPException: If the token has expired
    """
    exp = payload.get("exp")
    if exp is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has no expiration",
            headers={"WWW-Authenticate": "Bearer"},
        )

    exp_datetime = datetime.fromtimestamp(exp, tz=timezone.utc)
    if datetime.now(timezone.utc) > exp_datetime:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenData:
    """
    FastAPI dependency to extract and validate the current user from JWT.

    Usage:
        @app.get("/protected")
        async def protected_route(user: TokenData = Depends(get_current_user)):
            return {"email": user.email}

    Args:
        credentials: The HTTP Bearer credentials

    Returns:
        TokenData object with user information

    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials

    # Decode and validate token
    payload = decode_token(token)
    validate_token_expiry(payload)

    # Extract required fields
    email = payload.get("email")
    user_id = payload.get("userID")
    organization = payload.get("organization")
    platform = payload.get("platform")

    if not all([email, user_id, organization, platform]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenData(
        email=email,
        user_id=user_id,
        organization=organization,
        platform=platform,
        is_org_admin=payload.get("org_admin", 0),
        permissions=payload.get("permissions", {}),
        exp=datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc),
    )


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> Optional[TokenData]:
    """
    FastAPI dependency that optionally extracts user from JWT.
    Returns None if no token provided instead of raising an error.

    Usage:
        @app.get("/public-or-private")
        async def route(user: Optional[TokenData] = Depends(get_optional_user)):
            if user:
                return {"message": f"Hello {user.email}"}
            return {"message": "Hello anonymous"}
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


async def require_org_admin(
    current_user: TokenData = Depends(get_current_user),
) -> TokenData:
    """
    FastAPI dependency that requires the user to be an org admin.

    Usage:
        @router.post("/manage/...")
        async def admin_route(user: TokenData = Depends(require_org_admin)):
            ...

    Raises:
        HTTPException 403: If the user is not an org admin
    """
    if current_user.is_org_admin != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires org admin privileges",
        )
    return current_user
