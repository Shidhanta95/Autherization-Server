"""
Integration tests for end-to-end flows.

These tests require running services (use docker-compose for integration testing).
"""

import pytest
from unittest.mock import patch, AsyncMock


class TestHealthEndpoints:
    """Tests for health check endpoints"""

    def test_root_endpoint(self, client):
        """Test root endpoint returns status"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "version" in data

    def test_health_endpoint(self, client):
        """Test health endpoint"""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestFullLoginFlow:
    """Integration tests for complete login flow"""

    def test_login_to_callback_flow(
        self, client, mock_session_service, mock_opa_service
    ):
        """Test complete flow from login to callback"""
        # Step 1: Initiate login
        with patch("app.routers.auth.session_service", mock_session_service):
            login_response = client.post(
                "/api/v1/auth/login",
                json={"platform": "mlops", "org_name": "testorg"},
            )

        assert login_response.status_code == 200
        assert "login_url" in login_response.json()

        # Step 2: Simulate callback (normally user would authenticate with IdP)
        with (
            patch("app.routers.auth.session_service", mock_session_service),
            patch("app.routers.auth.opa_service", mock_opa_service),
            patch(
                "app.routers.auth.exchange_code_for_tokens", new_callable=AsyncMock
            ) as mock_exchange,
            patch(
                "app.routers.auth.verify_id_token", new_callable=AsyncMock
            ) as mock_verify,
        ):
            mock_exchange.return_value = {
                "id_token": "test-id-token",
                "access_token": "test-access-token",
            }
            mock_verify.return_value = {
                "email": "test@example.com",
                "name": "Test User",
            }

            callback_response = client.get(
                "/api/v1/auth/callback",
                params={"code": "test-auth-code", "state": "test-state"},
            )

        assert callback_response.status_code == 200
        data = callback_response.json()
        assert data["success"] is True
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["email"] == "test@example.com"


class TestTokenRefreshFlow:
    """Integration tests for token refresh flow"""

    def test_refresh_updates_permissions(
        self, client, mock_session_service, mock_opa_service
    ):
        """Test that refresh gets updated permissions from OPA"""
        # Create a valid refresh token
        from app.services.token_service import token_service
        from datetime import datetime, timedelta, timezone
        from jose import jwt
        from app.core.config import settings
        import uuid

        jti = str(uuid.uuid4())
        refresh_claims = {
            "email": "test@example.com",
            "platform": "mlops",
            "jti": jti,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(days=30),
            "type": "refresh",
        }
        refresh_token = jwt.encode(
            refresh_claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )

        # Mock session service to return valid token data
        mock_session_service.is_token_revoked.return_value = False
        mock_session_service.get_refresh_token.return_value = {
            "email": "test@example.com",
            "platform": "mlops",
        }

        # Update mock OPA to return NEW permissions
        new_permissions = {
            "projects": {"read": True, "write": True, "delete": True},
            "admin": {"read": True, "write": True, "delete": True},
        }
        mock_opa_service.get_user_permissions.return_value = new_permissions

        with (
            patch("app.routers.auth.session_service", mock_session_service),
            patch("app.routers.auth.opa_service", mock_opa_service),
            patch("app.services.token_service.session_service", mock_session_service),
        ):
            response = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

        # Decode the new access token and verify it has updated permissions
        decoded = jwt.decode(
            data["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        assert decoded["permissions"]["projects"]["delete"] is True


class TestAuthorizationFlow:
    """Integration tests for authorization flow"""

    def test_authorize_with_valid_token(
        self, client, valid_access_token, mock_opa_service
    ):
        """Test authorization with valid token"""
        with patch("app.routers.authorize.opa_service", mock_opa_service):
            response = client.post(
                "/api/v1/authorize",
                json={"resource": "projects", "action": "write"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["allowed"] is True

    def test_me_then_authorize(self, client, valid_access_token, mock_opa_service):
        """Test getting user info then checking authorization"""
        # Get user info
        me_response = client.get(
            "/api/v1/authorize/me",
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )

        assert me_response.status_code == 200
        user_data = me_response.json()
        assert "email" in user_data
        assert "permissions" in user_data

        # Now check authorization
        with patch("app.routers.authorize.opa_service", mock_opa_service):
            auth_response = client.post(
                "/api/v1/authorize",
                json={"resource": "projects", "action": "read"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert auth_response.status_code == 200
