"""
Token Service - Handles JWT token creation and management.

Supports:
- Access token generation
- Refresh token generation
- Token validation
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Tuple

from jose import jwt

from app.core.config import settings
from app.services.session_service import session_service


class TokenService:
    """Service for creating and managing JWT tokens"""

    def __init__(self):
        self.secret_key = settings.SECRET_KEY
        self.algorithm = settings.ALGORITHM
        self.access_token_expire_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
        self.refresh_token_expire_days = settings.REFRESH_TOKEN_EXPIRE_DAYS

    def create_access_token(
        self,
        email: str,
        user_id: str,
        organization: str,
        platform: str,
        permissions: Dict[str, Any],
        org_admin: int = 0,
        licence: Dict[str, Any] = None,
    ) -> Tuple[str, datetime]:
        """
        Create an access token with user claims.

        Args:
            email: User's email address
            user_id: User's unique identifier
            organization: Organization/tenant name
            platform: Platform name (mlops, analytics, etc.)
            permissions: User's permissions dict
            org_admin: 1 if org admin, 0 otherwise
            licence: Licence information to embed

        Returns:
            Tuple of (token_string, expiration_datetime)
        """
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=self.access_token_expire_minutes)

        # Use hardcoded licence if none provided
        if licence is None:
            licence = settings.HARDCODED_LICENCE.copy()
            licence["organization"] = organization

        claims = {
            "email": email,
            "userID": user_id,
            "organization": organization,
            "platform": platform,
            "org_admin": org_admin,
            "permissions": permissions,
            "licence": licence,
            "iat": now,
            "exp": expire,
            "type": "access",
        }

        token = jwt.encode(claims, self.secret_key, algorithm=self.algorithm)
        return token, expire

    async def create_refresh_token(
        self,
        email: str,
        platform: str,
    ) -> Tuple[str, datetime]:
        """
        Create a refresh token.

        Args:
            email: User's email address
            platform: Platform name

        Returns:
            Tuple of (token_string, expiration_datetime)
        """
        now = datetime.now(timezone.utc)
        expire = now + timedelta(days=self.refresh_token_expire_days)
        jti = str(uuid.uuid4())  # Unique token identifier

        claims = {
            "email": email,
            "platform": platform,
            "jti": jti,
            "iat": now,
            "exp": expire,
            "type": "refresh",
        }

        token = jwt.encode(claims, self.secret_key, algorithm=self.algorithm)

        # Store refresh token metadata in Redis
        expires_in_seconds = int((expire - now).total_seconds())
        await session_service.store_refresh_token(
            jti=jti,
            email=email,
            platform=platform,
            expires_in_seconds=expires_in_seconds,
        )

        return token, expire

    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decode a token without verification (for extracting claims).

        Args:
            token: The JWT token string

        Returns:
            The decoded claims

        Raises:
            JWTError: If the token is malformed
        """
        return jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
        )

    def validate_refresh_token(self, token: str) -> Dict[str, Any]:
        """
        Validate a refresh token and extract claims.

        Args:
            token: The refresh token string

        Returns:
            The decoded claims

        Raises:
            ValueError: If the token is invalid or not a refresh token
        """
        claims = self.decode_token(token)

        if claims.get("type") != "refresh":
            raise ValueError("Token is not a refresh token")

        return claims

    async def revoke_refresh_token(self, token: str) -> bool:
        """
        Revoke a refresh token.

        Args:
            token: The refresh token string

        Returns:
            True if revoked successfully
        """
        try:
            claims = self.decode_token(token)
            jti = claims.get("jti")

            if not jti:
                return False

            # Calculate remaining TTL
            exp = claims.get("exp")
            now = datetime.now(timezone.utc).timestamp()
            remaining_seconds = max(int(exp - now), 0)

            return await session_service.revoke_token(jti, remaining_seconds)

        except Exception as e:
            print(f"[TOKEN] Error revoking token: {e}")
            return False

    async def is_refresh_token_valid(self, token: str) -> bool:
        """
        Check if a refresh token is valid (not revoked, not expired).

        Args:
            token: The refresh token string

        Returns:
            True if valid, False otherwise
        """
        try:
            claims = self.validate_refresh_token(token)
            jti = claims.get("jti")

            if not jti:
                return False

            # Check if revoked
            if await session_service.is_token_revoked(jti):
                return False

            # Check if still in Redis (not expired)
            token_data = await session_service.get_refresh_token(jti)
            return token_data is not None

        except Exception:
            return False


# Singleton instance
token_service = TokenService()
