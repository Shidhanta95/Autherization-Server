"""
Tests for authorization endpoints.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


class TestAuthorizeEndpoint:
    """Tests for POST /api/v1/authorize"""

    def test_authorize_success(
        self, client: TestClient, valid_access_token, mock_opa_service
    ):
        """Test successful authorization check"""
        with patch("app.routers.authorize.opa_service", mock_opa_service):
            response = client.post(
                "/api/v1/authorize",
                json={"resource": "projects", "action": "write"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] is True
        assert "user_id" in data
        assert "organization" in data
        assert "role" in data

    def test_authorize_denied(
        self, client: TestClient, valid_access_token, mock_opa_service
    ):
        """Test authorization denied"""
        mock_opa_service.get_authorization_response.return_value = {
            "allowed": False,
            "user_id": "test-user-id",
            "organization": "testorg",
            "role": "viewer",
            "is_org_admin": 0,
        }

        with patch("app.routers.authorize.opa_service", mock_opa_service):
            response = client.post(
                "/api/v1/authorize",
                json={"resource": "projects", "action": "delete"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] is False

    def test_authorize_no_token(self, client: TestClient):
        """Test authorization without token"""
        response = client.post(
            "/api/v1/authorize",
            json={"resource": "projects", "action": "read"},
        )

        assert response.status_code == 403  # No credentials

    def test_authorize_invalid_token(self, client: TestClient):
        """Test authorization with invalid token"""
        response = client.post(
            "/api/v1/authorize",
            json={"resource": "projects", "action": "read"},
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401

    def test_authorize_expired_token(self, client: TestClient, expired_access_token):
        """Test authorization with expired token"""
        response = client.post(
            "/api/v1/authorize",
            json={"resource": "projects", "action": "read"},
            headers={"Authorization": f"Bearer {expired_access_token}"},
        )

        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    def test_authorize_missing_resource(self, client: TestClient, valid_access_token):
        """Test authorization with missing resource"""
        response = client.post(
            "/api/v1/authorize",
            json={"action": "read"},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )

        assert response.status_code == 422  # Validation error

    def test_authorize_with_context(
        self, client: TestClient, valid_access_token, mock_opa_service
    ):
        """Test authorization with additional context"""
        with patch("app.routers.authorize.opa_service", mock_opa_service):
            response = client.post(
                "/api/v1/authorize",
                json={
                    "resource": "projects",
                    "action": "write",
                    "context": {"project_id": "proj-123", "bu_id": "bu-456"},
                },
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200


class TestMeEndpoint:
    """Tests for GET /api/v1/authorize/me"""

    def test_me_success(self, client: TestClient, valid_access_token):
        """Test getting current user info"""
        response = client.get(
            "/api/v1/authorize/me",
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "email" in data
        assert "user_id" in data
        assert "organization" in data
        assert "platform" in data
        assert "permissions" in data

    def test_me_no_token(self, client: TestClient):
        """Test getting user info without token"""
        response = client.get("/api/v1/authorize/me")

        assert response.status_code == 403


class TestBatchAuthorizeEndpoint:
    """Tests for POST /api/v1/authorize/batch"""

    def test_batch_authorize_success(
        self, client: TestClient, valid_access_token, mock_opa_service
    ):
        """Test batch authorization check"""
        with patch("app.routers.authorize.opa_service", mock_opa_service):
            response = client.post(
                "/api/v1/authorize/batch",
                json=[
                    {"resource": "projects", "action": "read"},
                    {"resource": "projects", "action": "write"},
                    {"resource": "pipelines", "action": "delete"},
                ],
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 3
        assert all("allowed" in r for r in data["results"])

    def test_batch_authorize_empty(self, client: TestClient, valid_access_token):
        """Test batch authorization with empty list"""
        response = client.post(
            "/api/v1/authorize/batch",
            json=[],
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
