"""
Tests for OPA service.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from app.services.opa_service import OPAService


class TestOPAService:
    """Tests for OPAService"""

    @pytest.fixture
    def opa_service(self):
        return OPAService(opa_url="http://test-opa:8181")

    @pytest.mark.asyncio
    async def test_check_user_exists_true(self, opa_service):
        """Test user exists check returns True"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": True}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.check_user_exists("test@example.com")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_user_exists_false(self, opa_service):
        """Test user exists check returns False"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": False}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.check_user_exists("notexist@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_user_exists_opa_error(self, opa_service):
        """Test user exists check when OPA returns error"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.check_user_exists("test@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_user_context(self, opa_service):
        """Test getting user context"""
        expected_context = {
            "user_id": "user-123",
            "role": "admin",
            "organization": "testorg",
            "is_org_admin": 1,
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": expected_context}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.get_user_context("test@example.com", "mlops")

        assert result == expected_context

    @pytest.mark.asyncio
    async def test_get_user_permissions(self, opa_service):
        """Test getting user permissions"""
        expected_permissions = {
            "projects": {"read": True, "write": True, "delete": False},
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": expected_permissions}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.get_user_permissions("test@example.com", "mlops")

        assert result == expected_permissions

    @pytest.mark.asyncio
    async def test_get_user_permissions_empty(self, opa_service):
        """Test getting user permissions when none exist"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": None}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.get_user_permissions("test@example.com", "mlops")

        assert result == {}

    @pytest.mark.asyncio
    async def test_check_authorization_allowed(self, opa_service):
        """Test authorization check returns True"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": True}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.check_authorization(
                email="test@example.com",
                platform="mlops",
                resource="projects",
                action="write",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_authorization_denied(self, opa_service):
        """Test authorization check returns False"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": False}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.check_authorization(
                email="test@example.com",
                platform="mlops",
                resource="projects",
                action="delete",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_get_authorization_response(self, opa_service):
        """Test getting full authorization response"""
        expected_response = {
            "allowed": True,
            "user_id": "user-123",
            "organization": "testorg",
            "role": "admin",
            "is_org_admin": 1,
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": expected_response}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await opa_service.get_authorization_response(
                email="test@example.com",
                platform="mlops",
                resource="projects",
                action="write",
            )

        assert result == expected_response

    @pytest.mark.asyncio
    async def test_connection_error(self, opa_service):
        """Test handling connection errors to OPA"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )
            result = await opa_service.check_user_exists("test@example.com")

        assert result is False
