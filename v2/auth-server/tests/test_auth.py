"""
Tests for authentication endpoints.
"""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


class TestLoginEndpoint:
    """Tests for POST /api/v1/auth/login"""

    def test_login_success(self, client: TestClient, mock_session_service):
        """Test successful login initiation"""
        with patch("app.routers.auth.session_service", mock_session_service):
            response = client.post(
                "/api/v1/auth/login",
                json={"platform": "mlops", "org_name": "testorg"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "login_url" in data
        assert "okta.com" in data["login_url"] or "oauth2" in data["login_url"]

    def test_login_invalid_platform(self, client: TestClient):
        """Test login with invalid platform"""
        response = client.post(
            "/api/v1/auth/login",
            json={"platform": "invalid_platform", "org_name": "testorg"},
        )

        assert response.status_code == 400
        assert "Invalid platform" in response.json()["detail"]

    def test_login_missing_platform(self, client: TestClient):
        """Test login with missing platform"""
        response = client.post(
            "/api/v1/auth/login",
            json={"org_name": "testorg"},
        )

        assert response.status_code == 422  # Validation error

    def test_login_missing_org_name(self, client: TestClient):
        """Test login with missing org_name"""
        response = client.post(
            "/api/v1/auth/login",
            json={"platform": "mlops"},
        )

        assert response.status_code == 422  # Validation error

    def test_login_session_store_failure(
        self, client: TestClient, mock_session_service
    ):
        """Test login when session storage fails"""
        mock_session_service.store_login_state.return_value = False

        with patch("app.routers.auth.session_service", mock_session_service):
            response = client.post(
                "/api/v1/auth/login",
                json={"platform": "mlops", "org_name": "testorg"},
            )

        assert response.status_code == 500
        assert "Failed to initialize" in response.json()["detail"]


class TestCallbackEndpoint:
    """Tests for GET /api/v1/auth/callback"""

    def test_callback_invalid_state(self, client: TestClient, mock_session_service):
        """Test callback with invalid state"""
        mock_session_service.get_login_state.return_value = None

        with patch("app.routers.auth.session_service", mock_session_service):
            response = client.get(
                "/api/v1/auth/callback",
                params={"code": "test-code", "state": "invalid-state"},
            )

        assert response.status_code == 400
        assert "Invalid or expired state" in response.json()["detail"]

    def test_callback_missing_code(self, client: TestClient):
        """Test callback with missing code"""
        response = client.get(
            "/api/v1/auth/callback",
            params={"state": "test-state"},
        )

        assert response.status_code == 422  # Validation error

    def test_callback_user_not_registered(
        self, client: TestClient, mock_session_service, mock_opa_service
    ):
        """Test callback when user is not registered"""
        mock_opa_service.check_user_exists.return_value = False

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
            mock_verify.return_value = {"email": "notregistered@example.com"}

            response = client.get(
                "/api/v1/auth/callback",
                params={"code": "test-code", "state": "test-state"},
            )

        assert response.status_code == 403
        assert "not registered" in response.json()["detail"]


class TestRefreshEndpoint:
    """Tests for POST /api/v1/auth/refresh"""

    def test_refresh_invalid_token(self, client: TestClient):
        """Test refresh with invalid token"""
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid-token"},
        )

        assert response.status_code == 401

    def test_refresh_missing_token(self, client: TestClient):
        """Test refresh with missing token"""
        response = client.post(
            "/api/v1/auth/refresh",
            json={},
        )

        assert response.status_code == 422  # Validation error


class TestLogoutEndpoint:
    """Tests for POST /api/v1/auth/logout"""

    def test_logout_success(self, client: TestClient):
        """Test successful logout without token"""
        response = client.post(
            "/api/v1/auth/logout",
            json={},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_logout_with_invalid_token(self, client: TestClient):
        """Test logout with invalid refresh token"""
        response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "invalid-token"},
        )

        # Should still succeed but indicate token wasn't revoked
        assert response.status_code == 200
