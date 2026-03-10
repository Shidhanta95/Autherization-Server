"""
Comprehensive JWT Token Lifecycle Tests.

Tests the full token lifecycle:
1. Token Creation (Access + Refresh)
2. Token Validation
3. Token Expiration
4. Token Refresh Flow
5. Token Revocation
6. Token Tampering Detection
7. Permission Updates via Refresh
"""

import pytest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from jose import jwt, JWTError
import uuid

from app.services.token_service import TokenService
from app.core.config import settings


class TestTokenCreationLifecycle:
    """Test token creation phase of lifecycle"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    def test_access_token_structure(self, token_service):
        """Verify access token has all required claims"""
        token, expires = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={"projects": {"read": True, "write": True}},
            org_admin=1,
        )

        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        # Required claims
        assert "email" in decoded
        assert "userID" in decoded
        assert "organization" in decoded
        assert "platform" in decoded
        assert "org_admin" in decoded
        assert "permissions" in decoded
        assert "licence" in decoded
        assert "iat" in decoded
        assert "exp" in decoded
        assert "type" in decoded

        # Correct values
        assert decoded["email"] == "user@example.com"
        assert decoded["userID"] == "user-001"
        assert decoded["organization"] == "acme"
        assert decoded["platform"] == "mlops"
        assert decoded["org_admin"] == 1
        assert decoded["type"] == "access"

    @pytest.mark.asyncio
    async def test_refresh_token_structure(self, token_service, mock_session_service):
        """Verify refresh token has all required claims"""
        with patch("app.services.token_service.session_service", mock_session_service):
            token, expires = await token_service.create_refresh_token(
                email="user@example.com",
                platform="mlops",
            )

        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        # Required claims for refresh token
        assert "email" in decoded
        assert "platform" in decoded
        assert "jti" in decoded  # Unique token ID
        assert "iat" in decoded
        assert "exp" in decoded
        assert "type" in decoded

        # Should NOT have these (refresh tokens are minimal)
        assert "permissions" not in decoded
        assert "licence" not in decoded
        assert "userID" not in decoded

        assert decoded["type"] == "refresh"

    @pytest.mark.asyncio
    async def test_token_pair_creation(self, token_service, mock_session_service):
        """Test creating both access and refresh tokens together"""
        # Create access token
        access_token, access_expires = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={"projects": {"read": True}},
        )

        # Create refresh token
        with patch("app.services.token_service.session_service", mock_session_service):
            refresh_token, refresh_expires = await token_service.create_refresh_token(
                email="user@example.com",
                platform="mlops",
            )

        # Access token should expire sooner than refresh token
        assert access_expires < refresh_expires

        # Both should be valid JWTs
        access_decoded = jwt.decode(
            access_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        refresh_decoded = jwt.decode(
            refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        assert access_decoded["type"] == "access"
        assert refresh_decoded["type"] == "refresh"

        # Same user
        assert access_decoded["email"] == refresh_decoded["email"]
        assert access_decoded["platform"] == refresh_decoded["platform"]


class TestTokenValidationLifecycle:
    """Test token validation phase of lifecycle"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    def test_valid_token_decodes(self, token_service):
        """Test that valid tokens decode correctly"""
        token, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={},
        )

        decoded = token_service.decode_token(token)
        assert decoded["email"] == "user@example.com"

    def test_tampered_token_rejected(self, token_service):
        """Test that tampered tokens are rejected"""
        token, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={},
        )

        # Tamper with the token
        parts = token.split(".")
        tampered_token = parts[0] + "." + parts[1] + "x" + "." + parts[2]

        with pytest.raises(JWTError):
            token_service.decode_token(tampered_token)

    def test_wrong_secret_rejected(self, token_service):
        """Test that tokens signed with wrong secret are rejected"""
        # Create token with different secret
        claims = {
            "email": "user@example.com",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(claims, "wrong-secret-key", algorithm="HS256")

        with pytest.raises(JWTError):
            token_service.decode_token(token)

    def test_malformed_token_rejected(self, token_service):
        """Test that malformed tokens are rejected"""
        with pytest.raises(JWTError):
            token_service.decode_token("not-a-valid-jwt")

        with pytest.raises(JWTError):
            token_service.decode_token("a.b")

        with pytest.raises(JWTError):
            token_service.decode_token("")

    def test_refresh_token_validation(self, token_service):
        """Test refresh token specific validation"""
        # Create a proper refresh token
        claims = {
            "email": "user@example.com",
            "platform": "mlops",
            "jti": str(uuid.uuid4()),
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(days=30),
            "type": "refresh",
        }
        refresh_token = jwt.encode(
            claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )

        # Should validate successfully
        decoded = token_service.validate_refresh_token(refresh_token)
        assert decoded["type"] == "refresh"

    def test_access_token_fails_refresh_validation(self, token_service):
        """Test that access tokens fail refresh token validation"""
        access_token, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={},
        )

        with pytest.raises(ValueError, match="not a refresh token"):
            token_service.validate_refresh_token(access_token)


class TestTokenExpirationLifecycle:
    """Test token expiration handling"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    def test_expired_token_rejected(self, token_service):
        """Test that expired tokens are rejected"""
        # Create an already-expired token
        claims = {
            "email": "user@example.com",
            "type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc)
            - timedelta(hours=1),  # Expired 1 hour ago
        }
        expired_token = jwt.encode(
            claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )

        with pytest.raises(jwt.ExpiredSignatureError):
            token_service.decode_token(expired_token)

    def test_access_token_expiry_time(self, token_service):
        """Test access token expires at correct time"""
        token, expires = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={},
        )

        now = datetime.now(timezone.utc)
        expected_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES

        diff_minutes = (expires - now).total_seconds() / 60
        assert abs(diff_minutes - expected_minutes) < 1  # Within 1 minute tolerance

    @pytest.mark.asyncio
    async def test_refresh_token_expiry_time(self, token_service, mock_session_service):
        """Test refresh token expires at correct time"""
        with patch("app.services.token_service.session_service", mock_session_service):
            token, expires = await token_service.create_refresh_token(
                email="user@example.com",
                platform="mlops",
            )

        now = datetime.now(timezone.utc)
        expected_days = settings.REFRESH_TOKEN_EXPIRE_DAYS

        diff_days = (expires - now).total_seconds() / (60 * 60 * 24)
        assert abs(diff_days - expected_days) < 0.1  # Within ~2.4 hours tolerance

    def test_token_near_expiry(self, token_service):
        """Test token that is close to expiry but still valid"""
        # Create a token that expires in 1 second
        claims = {
            "email": "user@example.com",
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=5),
        }
        token = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        # Should still be valid
        decoded = token_service.decode_token(token)
        assert decoded["email"] == "user@example.com"


class TestTokenRevocationLifecycle:
    """Test token revocation flow"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    @pytest.mark.asyncio
    async def test_revoke_refresh_token(self, token_service, mock_session_service):
        """Test revoking a refresh token"""
        # Create refresh token
        with patch("app.services.token_service.session_service", mock_session_service):
            token, _ = await token_service.create_refresh_token(
                email="user@example.com",
                platform="mlops",
            )

        # Revoke it
        mock_session_service.revoke_token = AsyncMock(return_value=True)
        with patch("app.services.token_service.session_service", mock_session_service):
            result = await token_service.revoke_refresh_token(token)

        assert result is True
        mock_session_service.revoke_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoked_token_invalid(self, token_service, mock_session_service):
        """Test that revoked tokens are marked invalid"""
        # Create refresh token
        with patch("app.services.token_service.session_service", mock_session_service):
            token, _ = await token_service.create_refresh_token(
                email="user@example.com",
                platform="mlops",
            )

        # Mock revocation check to return True (token is revoked)
        mock_session_service.is_token_revoked = AsyncMock(return_value=True)

        with patch("app.services.token_service.session_service", mock_session_service):
            is_valid = await token_service.is_refresh_token_valid(token)

        assert is_valid is False

    @pytest.mark.asyncio
    async def test_valid_unrevoked_token(self, token_service, mock_session_service):
        """Test that unrevoked tokens are valid"""
        # Create refresh token
        with patch("app.services.token_service.session_service", mock_session_service):
            token, _ = await token_service.create_refresh_token(
                email="user@example.com",
                platform="mlops",
            )

        # Get the jti from the token
        decoded = token_service.validate_refresh_token(token)
        jti = decoded["jti"]

        # Mock: not revoked, and exists in Redis
        mock_session_service.is_token_revoked = AsyncMock(return_value=False)
        mock_session_service.get_refresh_token = AsyncMock(
            return_value={
                "email": "user@example.com",
                "platform": "mlops",
            }
        )

        with patch("app.services.token_service.session_service", mock_session_service):
            is_valid = await token_service.is_refresh_token_valid(token)

        assert is_valid is True


class TestTokenRefreshLifecycle:
    """Test the token refresh flow"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    @pytest.mark.asyncio
    async def test_refresh_flow_new_permissions(
        self, token_service, mock_session_service
    ):
        """Test that refreshing gets new permissions"""
        # Original permissions
        old_permissions = {"projects": {"read": True}}

        # Create original access token
        access_token_1, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions=old_permissions,
        )

        # Verify original permissions
        decoded_1 = token_service.decode_token(access_token_1)
        assert decoded_1["permissions"] == old_permissions

        # Simulate permission update in OPA
        new_permissions = {"projects": {"read": True, "write": True, "delete": True}}

        # Create new access token with updated permissions (simulating refresh)
        access_token_2, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions=new_permissions,  # New permissions from OPA
        )

        # Verify new permissions
        decoded_2 = token_service.decode_token(access_token_2)
        assert decoded_2["permissions"] == new_permissions
        assert decoded_2["permissions"]["projects"]["write"] is True
        assert decoded_2["permissions"]["projects"]["delete"] is True

    @pytest.mark.asyncio
    async def test_refresh_token_reuse(self, token_service, mock_session_service):
        """Test that refresh token can be used multiple times (no rotation)"""
        # Create refresh token
        with patch("app.services.token_service.session_service", mock_session_service):
            refresh_token, _ = await token_service.create_refresh_token(
                email="user@example.com",
                platform="mlops",
            )

        # Get jti
        decoded = token_service.validate_refresh_token(refresh_token)
        original_jti = decoded["jti"]

        # Validate multiple times (simulating multiple refresh requests)
        for i in range(3):
            decoded = token_service.validate_refresh_token(refresh_token)
            assert decoded["jti"] == original_jti  # Same jti each time
            assert decoded["email"] == "user@example.com"


class TestTokenSecurityLifecycle:
    """Test security aspects of token lifecycle"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    def test_token_contains_no_sensitive_data(self, token_service):
        """Ensure tokens don't contain passwords or secrets"""
        token, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={"projects": {"read": True}},
        )

        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        # Should not contain these
        assert "password" not in decoded
        assert "secret" not in decoded
        assert "api_key" not in decoded

    def test_tokens_are_unique(self, token_service):
        """Test that each token generation produces unique tokens"""
        tokens = []

        for i in range(5):
            token, _ = token_service.create_access_token(
                email=f"user{i}@example.com",  # Different email each time
                user_id=f"user-{i:03d}",
                organization="acme",
                platform="mlops",
                permissions={},
            )
            tokens.append(token)

        # All tokens should be unique (different claims)
        assert len(set(tokens)) == 5

        # Verify each token has correct email
        for i, token in enumerate(tokens):
            decoded = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            assert decoded["email"] == f"user{i}@example.com"

    @pytest.mark.asyncio
    async def test_refresh_tokens_have_unique_jti(
        self, token_service, mock_session_service
    ):
        """Test that each refresh token has a unique JTI"""
        jtis = set()

        with patch("app.services.token_service.session_service", mock_session_service):
            for _ in range(10):
                token, _ = await token_service.create_refresh_token(
                    email="user@example.com",
                    platform="mlops",
                )
                decoded = token_service.validate_refresh_token(token)
                jtis.add(decoded["jti"])

        # All JTIs should be unique
        assert len(jtis) == 10

    def test_algorithm_consistency(self, token_service):
        """Test that tokens use the configured algorithm"""
        token, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={},
        )

        # Decode header to verify algorithm
        header = jwt.get_unverified_header(token)
        assert header["alg"] == settings.ALGORITHM


class TestLicenceInToken:
    """Test licence handling in tokens"""

    @pytest.fixture
    def token_service(self):
        return TokenService()

    def test_default_licence_included(self, token_service):
        """Test that default licence is included when none provided"""
        token, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={},
        )

        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        assert "licence" in decoded
        assert decoded["licence"]["organization"] == "acme"

    def test_custom_licence_included(self, token_service):
        """Test that custom licence overrides default"""
        custom_licence = {
            "organization": "custom-org",
            "tier": "enterprise",
            "max_users": 1000,
            "features": ["advanced", "premium"],
        }

        token, _ = token_service.create_access_token(
            email="user@example.com",
            user_id="user-001",
            organization="acme",
            platform="mlops",
            permissions={},
            licence=custom_licence,
        )

        decoded = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        assert decoded["licence"] == custom_licence
        assert decoded["licence"]["tier"] == "enterprise"
