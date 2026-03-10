"""
Test configuration and fixtures for Auth Server tests.
"""

import os
import pytest
from typing import Generator, Dict, Any
from unittest.mock import AsyncMock, MagicMock

# Set test environment variables before importing app
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["OKTA_DOMAIN"] = "test.okta.com"
os.environ["OKTA_ISSUER"] = "https://test.okta.com/oauth2/default"
os.environ["OKTA_CLIENT_ID"] = "test-client-id"
os.environ["OKTA_CLIENT_SECRET"] = "test-client-secret"
os.environ["REDIRECT_URI"] = "http://localhost:8000/api/v1/auth/callback"
os.environ["OPA_URL"] = "http://localhost:8181"
os.environ["REDIS_URL"] = "redis://localhost:6379"

from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app
from app.core.config import settings
from app.services.token_service import token_service


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Synchronous test client for FastAPI"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def async_client() -> Generator[AsyncClient, None, None]:
    """Asynchronous test client for FastAPI"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_user_context() -> Dict[str, Any]:
    """Mock user context from OPA"""
    return {
        "user_id": "test-user-id-123",
        "role": "admin",
        "organization": "testorg",
        "is_org_admin": 1,
    }


@pytest.fixture
def mock_permissions() -> Dict[str, Any]:
    """Mock permissions from OPA"""
    return {
        "projects": {"read": True, "write": True, "delete": True},
        "pipelines": {"read": True, "write": False, "delete": False},
        "experiments": {"read": True, "write": True, "delete": False},
    }


@pytest.fixture
def mock_role_metadata() -> Dict[str, Any]:
    """Mock role metadata from OPA"""
    return {
        "global_access": True,
        "bu_access": False,
    }


@pytest.fixture
def valid_access_token(mock_user_context, mock_permissions) -> str:
    """Generate a valid access token for testing"""
    token, _ = token_service.create_access_token(
        email="test@example.com",
        user_id=mock_user_context["user_id"],
        organization=mock_user_context["organization"],
        platform="mlops",
        permissions=mock_permissions,
        org_admin=mock_user_context["is_org_admin"],
    )
    return token


@pytest.fixture
def expired_access_token() -> str:
    """Generate an expired access token for testing"""
    from datetime import datetime, timedelta, timezone
    from jose import jwt

    claims = {
        "email": "test@example.com",
        "userID": "test-user-id",
        "organization": "testorg",
        "platform": "mlops",
        "permissions": {},
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        "type": "access",
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@pytest.fixture
def mock_opa_service(mock_user_context, mock_permissions, mock_role_metadata):
    """Mock OPA service for testing"""
    mock = AsyncMock()
    mock.check_user_exists.return_value = True
    mock.get_user_context.return_value = mock_user_context
    mock.get_user_permissions.return_value = mock_permissions
    mock.get_role_metadata.return_value = mock_role_metadata
    mock.check_authorization.return_value = True
    mock.get_authorization_response.return_value = {
        "allowed": True,
        "user_id": mock_user_context["user_id"],
        "organization": mock_user_context["organization"],
        "role": mock_user_context["role"],
        "is_org_admin": mock_user_context["is_org_admin"],
    }
    return mock


@pytest.fixture
def mock_session_service():
    """Mock session service for testing"""
    mock = AsyncMock()
    mock.store_login_state.return_value = True
    mock.get_login_state.return_value = {
        "platform": "mlops",
        "org_name": "testorg",
        "nonce": "test-nonce",
    }
    mock.delete_login_state.return_value = True
    mock.store_refresh_token.return_value = True
    mock.get_refresh_token.return_value = {
        "email": "test@example.com",
        "platform": "mlops",
    }
    mock.is_token_revoked.return_value = False
    return mock
