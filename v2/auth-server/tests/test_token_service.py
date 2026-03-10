"""
Tests for token service.
"""

import pytest
from datetime import datetime, timezone
from jose import jwt

from app.services.token_service import TokenService
from app.core.config import settings


class TestTokenService:
    """Tests for TokenService"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    def test_create_access_token(self, token_service):
        """Test access token creation"""
        token, expires = token_service.create_access_token(
            email="test@example.com",
            user_id="user-123",
            organization="testorg",
            platform="mlops",
            permissions={"projects": {"read": True}},
            org_admin=1,
        )

        # Verify token is valid JWT
        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        assert decoded["email"] == "test@example.com"
        assert decoded["userID"] == "user-123"
        assert decoded["organization"] == "testorg"
        assert decoded["platform"] == "mlops"
        assert decoded["org_admin"] == 1
        assert decoded["type"] == "access"
        assert "permissions" in decoded
        assert "licence" in decoded
        assert "exp" in decoded
        assert "iat" in decoded

    def test_access_token_expiry(self, token_service):
        """Test access token has correct expiry"""
        token, expires = token_service.create_access_token(
            email="test@example.com",
            user_id="user-123",
            organization="testorg",
            platform="mlops",
            permissions={},
        )

        # Expiry should be approximately ACCESS_TOKEN_EXPIRE_MINUTES from now
        now = datetime.now(timezone.utc)
        expected_expiry_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES

        diff_minutes = (expires - now).total_seconds() / 60
        assert abs(diff_minutes - expected_expiry_minutes) < 1  # Within 1 minute

    @pytest.mark.asyncio
    async def test_create_refresh_token(self, token_service, mock_session_service):
        """Test refresh token creation"""
        from unittest.mock import patch

        with patch("app.services.token_service.session_service", mock_session_service):
            token, expires = await token_service.create_refresh_token(
                email="test@example.com",
                platform="mlops",
            )

        # Verify token is valid JWT
        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        assert decoded["email"] == "test@example.com"
        assert decoded["platform"] == "mlops"
        assert decoded["type"] == "refresh"
        assert "jti" in decoded  # Unique token ID
        assert "exp" in decoded

    def test_decode_token(self, token_service):
        """Test token decoding"""
        # Create a token
        token, _ = token_service.create_access_token(
            email="test@example.com",
            user_id="user-123",
            organization="testorg",
            platform="mlops",
            permissions={},
        )

        # Decode it
        decoded = token_service.decode_token(token)

        assert decoded["email"] == "test@example.com"

    def test_validate_refresh_token(self, token_service):
        """Test refresh token validation"""
        # Create a refresh token directly
        from datetime import timedelta
        import uuid

        claims = {
            "email": "test@example.com",
            "platform": "mlops",
            "jti": str(uuid.uuid4()),
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(days=30),
            "type": "refresh",
        }
        token = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        # Validate it
        decoded = token_service.validate_refresh_token(token)
        assert decoded["type"] == "refresh"

    def test_validate_refresh_token_wrong_type(self, token_service):
        """Test validation fails for non-refresh token"""
        # Create an access token
        token, _ = token_service.create_access_token(
            email="test@example.com",
            user_id="user-123",
            organization="testorg",
            platform="mlops",
            permissions={},
        )

        # Should fail validation as refresh token
        with pytest.raises(ValueError, match="not a refresh token"):
            token_service.validate_refresh_token(token)


class TestTokenServiceEdgeCases:
    """Edge case tests for TokenService"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    def test_create_token_with_special_characters_in_email(self, token_service):
        """Test token creation with special email characters"""
        token, _ = token_service.create_access_token(
            email="user+test@example.com",
            user_id="user-123",
            organization="test-org",
            platform="mlops",
            permissions={},
        )

        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        assert decoded["email"] == "user+test@example.com"

    def test_create_token_with_empty_permissions(self, token_service):
        """Test token creation with empty permissions"""
        token, _ = token_service.create_access_token(
            email="test@example.com",
            user_id="user-123",
            organization="testorg",
            platform="mlops",
            permissions={},
        )

        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        assert decoded["permissions"] == {}

    def test_create_token_with_complex_permissions(self, token_service):
        """Test token creation with complex permissions structure"""
        complex_permissions = {
            "projects": {"read": True, "write": True, "delete": False},
            "pipelines": {"read": True, "write": False, "delete": False},
            "global_access": True,
            "bu_access": False,
        }

        token, _ = token_service.create_access_token(
            email="test@example.com",
            user_id="user-123",
            organization="testorg",
            platform="mlops",
            permissions=complex_permissions,
        )

        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        assert decoded["permissions"] == complex_permissions
