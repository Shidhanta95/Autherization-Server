"""
OPA Service - HTTP client for querying Open Policy Agent.

Handles:
- User existence checks
- User context retrieval
- Permission queries
- Authorization decisions
"""

from typing import Optional, Dict, Any
import httpx

from app.core.config import settings


class OPAService:
    """Service for interacting with Open Policy Agent"""

    def __init__(self, opa_url: str = None):
        self.opa_url = opa_url or settings.OPA_URL

    async def _query(self, path: str, input_data: dict) -> Optional[dict]:
        """
        Execute a query against OPA.

        Args:
            path: The OPA data path (e.g., "authz/user_exists")
            input_data: The input data for the query

        Returns:
            The query result or None if not found
        """
        url = f"{self.opa_url}/v1/data/{path}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    json={"input": input_data},
                    headers={"Content-Type": "application/json"},
                    timeout=10.0,
                )

                if response.status_code == 200:
                    result = response.json()
                    return result.get("result")
                else:
                    print(
                        f"[OPA] Query failed: {response.status_code} - {response.text}"
                    )
                    return None

            except httpx.RequestError as e:
                print(f"[OPA] Request error: {e}")
                return None

    async def check_user_exists(self, email: str) -> bool:
        """
        Check if a user exists in the authorization system.

        Args:
            email: The user's email address

        Returns:
            True if user exists, False otherwise
        """
        result = await self._query("authz/user_exists", {"user": email})
        return result is True

    async def get_user_context(
        self, email: str, platform: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get user context for JWT creation.

        Args:
            email: The user's email address
            platform: The platform name (e.g., "mlops")

        Returns:
            Dict with user_id, role, organization, is_org_admin
            or None if user not found
        """
        result = await self._query(
            "authz/user_context", {"user": email, "platform": platform}
        )
        return result

    async def get_user_permissions(
        self, email: str, platform: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get all permissions for a user on a platform.

        Args:
            email: The user's email address
            platform: The platform name

        Returns:
            Dict of resource permissions or None if not found
        """
        result = await self._query(
            "authz/user_permissions", {"user": email, "platform": platform}
        )
        return result or {}

    async def get_role_metadata(
        self, email: str, platform: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get role metadata (global_access, bu_access).

        Args:
            email: The user's email address
            platform: The platform name

        Returns:
            Dict with global_access and bu_access flags
        """
        result = await self._query(
            "authz/role_metadata", {"user": email, "platform": platform}
        )
        return result or {"global_access": False, "bu_access": False}

    async def check_authorization(
        self, email: str, platform: str, resource: str, action: str
    ) -> bool:
        """
        Check if a user is authorized to perform an action on a resource.

        Args:
            email: The user's email address
            platform: The platform name
            resource: The resource name (e.g., "projects")
            action: The action (e.g., "read", "write", "delete")

        Returns:
            True if authorized, False otherwise
        """
        result = await self._query(
            "authz/allow",
            {
                "user": email,
                "platform": platform,
                "resource": resource,
                "action": action,
            },
        )
        return result is True

    async def get_authorization_response(
        self, email: str, platform: str, resource: str, action: str
    ) -> Dict[str, Any]:
        """
        Get full authorization response with context.

        Args:
            email: The user's email address
            platform: The platform name
            resource: The resource name
            action: The action

        Returns:
            Dict with allowed, user_id, organization, role, is_org_admin
        """
        result = await self._query(
            "authz/authorization_response",
            {
                "user": email,
                "platform": platform,
                "resource": resource,
                "action": action,
            },
        )

        if result:
            return result

        # Return default unauthorized response
        return {
            "allowed": False,
            "user_id": None,
            "organization": None,
            "role": None,
            "is_org_admin": 0,
        }


# Singleton instance
opa_service = OPAService()
