"""
Session Service - Manages login state using Redis.

Handles:
- Storing login state (platform, org_name) between /login and /callback
- State validation for CSRF protection
- Session cleanup
"""

import json
from typing import Optional, Dict, Any

import redis.asyncio as redis

from app.core.config import settings


class SessionService:
    """Service for managing login sessions in Redis"""

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional[redis.Redis] = None

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection"""
        if self._redis is None:
            self._redis = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def close(self):
        """Close Redis connection"""
        if self._redis:
            await self._redis.close()
            self._redis = None

    def _state_key(self, state: str) -> str:
        """Generate Redis key for a state"""
        return f"login_state:{state}"

    def _refresh_token_key(self, jti: str) -> str:
        """Generate Redis key for a refresh token"""
        return f"refresh_token:{jti}"

    def _revoked_token_key(self, jti: str) -> str:
        """Generate Redis key for a revoked token"""
        return f"revoked_token:{jti}"

    # ============================================================
    # LOGIN STATE MANAGEMENT
    # ============================================================

    async def store_login_state(
        self,
        state: str,
        platform: str,
        org_name: str,
        nonce: str = None,
    ) -> bool:
        """
        Store login state for the SSO flow.

        Args:
            state: The OAuth state parameter
            platform: The platform being logged into
            org_name: The organization name
            nonce: The OIDC nonce (optional)

        Returns:
            True if stored successfully
        """
        try:
            r = await self._get_redis()

            data = {
                "platform": platform,
                "org_name": org_name,
                "nonce": nonce,
            }

            await r.setex(
                self._state_key(state),
                settings.SESSION_TTL_SECONDS,
                json.dumps(data),
            )

            return True

        except Exception as e:
            print(f"[SESSION] Error storing login state: {e}")
            return False

    async def get_login_state(self, state: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve login state for the SSO callback.

        Args:
            state: The OAuth state parameter

        Returns:
            Dict with platform, org_name, nonce or None if not found
        """
        try:
            r = await self._get_redis()
            data = await r.get(self._state_key(state))

            if data:
                return json.loads(data)

            return None

        except Exception as e:
            print(f"[SESSION] Error retrieving login state: {e}")
            return None

    async def delete_login_state(self, state: str) -> bool:
        """
        Delete login state after use.

        Args:
            state: The OAuth state parameter

        Returns:
            True if deleted successfully
        """
        try:
            r = await self._get_redis()
            await r.delete(self._state_key(state))
            return True

        except Exception as e:
            print(f"[SESSION] Error deleting login state: {e}")
            return False

    # ============================================================
    # REFRESH TOKEN MANAGEMENT
    # ============================================================

    async def store_refresh_token(
        self,
        jti: str,
        email: str,
        platform: str,
        expires_in_seconds: int,
    ) -> bool:
        """
        Store refresh token metadata.

        Args:
            jti: The token's unique identifier
            email: The user's email
            platform: The platform
            expires_in_seconds: Token TTL

        Returns:
            True if stored successfully
        """
        try:
            r = await self._get_redis()

            data = {
                "email": email,
                "platform": platform,
            }

            await r.setex(
                self._refresh_token_key(jti),
                expires_in_seconds,
                json.dumps(data),
            )

            return True

        except Exception as e:
            print(f"[SESSION] Error storing refresh token: {e}")
            return False

    async def get_refresh_token(self, jti: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve refresh token metadata.

        Args:
            jti: The token's unique identifier

        Returns:
            Dict with email, platform or None if not found/expired
        """
        try:
            r = await self._get_redis()
            data = await r.get(self._refresh_token_key(jti))

            if data:
                return json.loads(data)

            return None

        except Exception as e:
            print(f"[SESSION] Error retrieving refresh token: {e}")
            return None

    async def delete_refresh_token(self, jti: str) -> bool:
        """
        Delete a refresh token (logout).

        Args:
            jti: The token's unique identifier

        Returns:
            True if deleted successfully
        """
        try:
            r = await self._get_redis()
            await r.delete(self._refresh_token_key(jti))
            return True

        except Exception as e:
            print(f"[SESSION] Error deleting refresh token: {e}")
            return False

    # ============================================================
    # TOKEN REVOCATION
    # ============================================================

    async def revoke_token(self, jti: str, expires_in_seconds: int) -> bool:
        """
        Add a token to the revocation list.

        Args:
            jti: The token's unique identifier
            expires_in_seconds: How long to keep in revocation list

        Returns:
            True if revoked successfully
        """
        try:
            r = await self._get_redis()

            await r.setex(
                self._revoked_token_key(jti),
                expires_in_seconds,
                "revoked",
            )

            # Also delete from refresh token store
            await self.delete_refresh_token(jti)

            return True

        except Exception as e:
            print(f"[SESSION] Error revoking token: {e}")
            return False

    async def is_token_revoked(self, jti: str) -> bool:
        """
        Check if a token has been revoked.

        Args:
            jti: The token's unique identifier

        Returns:
            True if revoked, False otherwise
        """
        try:
            r = await self._get_redis()
            return await r.exists(self._revoked_token_key(jti)) > 0

        except Exception as e:
            print(f"[SESSION] Error checking revocation: {e}")
            return False


# Singleton instance
session_service = SessionService()
