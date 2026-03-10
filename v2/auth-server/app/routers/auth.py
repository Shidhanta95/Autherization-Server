"""
Authentication Router - Handles SSO login, callback, token refresh, and logout.
"""

import uuid
from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, status
import httpx

from app.core.config import settings
from app.models.schemas import (
    LoginRequest,
    TestLoginRequest,
    LoginResponse,
    CallbackResponse,
    RefreshRequest,
    TokenResponse,
    LogoutRequest,
    LogoutResponse,
)
from app.services import (
    get_sso_config_for_org,
    create_authorization_url,
    exchange_code_for_tokens,
    verify_id_token,
    opa_service,
    session_service,
    token_service,
)


router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Authentication"],
)


# ============================================================
# LOGIN ENDPOINT
# ============================================================


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Initiate SSO Login",
    description="Start the SSO flow by getting the IdP authorization URL.",
)
async def login(request: LoginRequest):
    """
    Initiate SSO login flow.

    1. Validates the platform
    2. Gets SSO configuration for the organization
    3. Generates authorization URL with state
    4. Stores state in Redis for callback validation
    5. Returns the login URL for the frontend to redirect
    """
    # Validate platform
    if request.platform not in settings.PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform: {request.platform}. Valid platforms: {settings.PLATFORMS}",
        )

    # Get SSO config for organization
    sso_config = await get_sso_config_for_org(request.org_name)
    if not sso_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SSO not configured for organization: {request.org_name}",
        )

    # Generate state for CSRF protection
    state = str(uuid.uuid4())

    # Create authorization URL
    login_url, nonce = create_authorization_url(
        client_id=sso_config["client_id"],
        issuer=sso_config["issuer"],
        state=state,
    )

    # Store state in Redis
    stored = await session_service.store_login_state(
        state=state,
        platform=request.platform,
        org_name=request.org_name,
        nonce=nonce,
    )

    if not stored:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize login session",
        )

    return LoginResponse(login_url=login_url)


# ============================================================
# CALLBACK ENDPOINT
# ============================================================


@router.get(
    "/callback",
    response_model=CallbackResponse,
    summary="SSO Callback",
    description="Handle the IdP callback after successful authentication.",
)
async def callback(
    code: str = Query(..., description="Authorization code from IdP"),
    state: str = Query(..., description="State parameter for CSRF validation"),
):
    """
    Handle SSO callback from IdP.

    1. Validates state parameter
    2. Exchanges authorization code for tokens
    3. Verifies ID token
    4. Checks user exists in authorization system (OPA)
    5. Fetches user context and permissions
    6. Creates access and refresh tokens
    7. Returns tokens to frontend
    """
    # Retrieve login state from Redis
    login_state = await session_service.get_login_state(state)
    if not login_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter. Please restart login.",
        )

    platform = login_state["platform"]
    org_name = login_state["org_name"]

    try:
        # Exchange code for tokens
        token_data = await exchange_code_for_tokens(code)
        id_token = token_data.get("id_token")
        access_token = token_data.get("access_token")

        if not id_token or not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID or Access token not found in IdP response",
            )

        # Verify ID token
        claims = await verify_id_token(id_token, access_token)
        if not claims:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid ID token from IdP",
            )

        email = claims.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not found in token claims",
            )

        # Check user exists in authorization system
        user_exists = await opa_service.check_user_exists(email)
        if not user_exists:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User {email} is not registered in the system. Contact your administrator.",
            )

        # Get user context from OPA
        user_context = await opa_service.get_user_context(email, platform)
        if not user_context:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User {email} has no access to platform {platform}",
            )

        # Get user permissions from OPA
        permissions = await opa_service.get_user_permissions(email, platform)

        # Get role metadata (global_access, bu_access)
        role_metadata = await opa_service.get_role_metadata(email, platform)

        # Merge permissions with role metadata
        full_permissions = {
            **permissions,
            "global_access": role_metadata.get("global_access", False),
            "bu_access": role_metadata.get("bu_access", False),
        }

        # Create access token
        app_access_token, access_expires = token_service.create_access_token(
            email=email,
            user_id=user_context["user_id"],
            organization=user_context["organization"],
            platform=platform,
            permissions=full_permissions,
            org_admin=user_context.get("is_org_admin", 0),
        )

        # Create refresh token
        refresh_token, _ = await token_service.create_refresh_token(
            email=email,
            platform=platform,
        )

        # Calculate expires_in
        from datetime import datetime

        expires_in = int((access_expires - datetime.now(timezone.utc)).total_seconds())

        # Clean up login state
        await session_service.delete_login_state(state)

        return CallbackResponse(
            success=True,
            email=email,
            organization=user_context["organization"],
            user_id=user_context["user_id"],
            access_token=app_access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=expires_in,
            message="Successfully logged in via SSO",
        )

    except httpx.HTTPStatusError as e:
        error_detail = "Error communicating with IdP"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error_description", e.response.text)
        except Exception:
            error_detail = e.response.text

        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"IdP error: {error_detail}",
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during authentication: {str(e)}",
        )


# ============================================================
# REFRESH ENDPOINT
# ============================================================


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh Access Token",
    description="Exchange a refresh token for a new access token.",
)
async def refresh(request: RefreshRequest):
    """
    Refresh access token.

    1. Validates refresh token
    2. Checks token is not revoked
    3. Queries OPA for latest user permissions
    4. Creates new access token with updated permissions
    5. Returns new access token (same refresh token)
    """
    # Validate refresh token
    try:
        claims = token_service.validate_refresh_token(request.refresh_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid refresh token: {str(e)}",
        )

    # Check if token is valid (not revoked)
    is_valid = await token_service.is_refresh_token_valid(request.refresh_token)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked or expired",
        )

    email = claims.get("email")
    platform = claims.get("platform")

    # Check user still exists
    user_exists = await opa_service.check_user_exists(email)
    if not user_exists:
        # Revoke the refresh token since user no longer exists
        await token_service.revoke_refresh_token(request.refresh_token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists in the system",
        )

    # Get fresh user context and permissions from OPA
    user_context = await opa_service.get_user_context(email, platform)
    if not user_context:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User no longer has access to platform {platform}",
        )

    permissions = await opa_service.get_user_permissions(email, platform)
    role_metadata = await opa_service.get_role_metadata(email, platform)

    full_permissions = {
        **permissions,
        "global_access": role_metadata.get("global_access", False),
        "bu_access": role_metadata.get("bu_access", False),
    }

    # Create new access token with fresh permissions
    access_token, access_expires = token_service.create_access_token(
        email=email,
        user_id=user_context["user_id"],
        organization=user_context["organization"],
        platform=platform,
        permissions=full_permissions,
        org_admin=user_context.get("is_org_admin", 0),
    )

    from datetime import datetime

    expires_in = int((access_expires - datetime.now(timezone.utc)).total_seconds())

    return TokenResponse(
        access_token=access_token,
        refresh_token=request.refresh_token,  # Return same refresh token
        token_type="Bearer",
        expires_in=expires_in,
    )


# ============================================================
# LOGOUT ENDPOINT
# ============================================================


# ============================================================
# TEST LOGIN ENDPOINT (Development/Testing Only)
# ============================================================


@router.post(
    "/test-login",
    response_model=CallbackResponse,
    summary="Test Login (Dev Only)",
    description="Bypass SSO for testing. Only available in non-production environments.",
    include_in_schema=settings.DEBUG,
)
async def test_login(request: TestLoginRequest):
    """
    Test login endpoint that bypasses SSO.

    WARNING: This endpoint should only be enabled in development/testing environments.
    It allows direct login without IdP authentication for E2E testing purposes.
    """
    # Only allow in debug mode
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not available",
        )

    # Validate platform
    if request.platform not in settings.PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform: {request.platform}. Valid platforms: {settings.PLATFORMS}",
        )

    email = request.email

    # Check user exists in authorization system
    user_exists = await opa_service.check_user_exists(email)
    if not user_exists:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User {email} is not registered in the system. Contact your administrator.",
        )

    # Get user context from OPA
    user_context = await opa_service.get_user_context(email, request.platform)
    if not user_context:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User {email} has no access to platform {request.platform}",
        )

    # Get user permissions from OPA
    permissions = await opa_service.get_user_permissions(email, request.platform)

    # Get role metadata
    role_metadata = await opa_service.get_role_metadata(email, request.platform)

    # Merge permissions with role metadata
    full_permissions = {
        **permissions,
        "global_access": role_metadata.get("global_access", False),
        "bu_access": role_metadata.get("bu_access", False),
    }

    # Create access token
    app_access_token, access_expires = token_service.create_access_token(
        email=email,
        user_id=user_context["user_id"],
        organization=user_context["organization"],
        platform=request.platform,
        permissions=full_permissions,
        org_admin=user_context.get("is_org_admin", 0),
    )

    # Create refresh token
    refresh_token, _ = await token_service.create_refresh_token(
        email=email,
        platform=request.platform,
    )

    # Calculate expires_in
    from datetime import datetime

    expires_in = int((access_expires - datetime.now(timezone.utc)).total_seconds())

    return CallbackResponse(
        success=True,
        email=email,
        organization=user_context["organization"],
        user_id=user_context["user_id"],
        access_token=app_access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=expires_in,
        message="Test login successful (bypassed SSO)",
    )


# ============================================================
# LOGOUT ENDPOINT
# ============================================================


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout",
    description="Revoke refresh token and logout.",
)
async def logout(request: LogoutRequest):
    """
    Logout user by revoking their refresh token.

    If refresh_token is provided, revokes that specific token.
    """
    if request.refresh_token:
        revoked = await token_service.revoke_refresh_token(request.refresh_token)
        if revoked:
            return LogoutResponse(
                success=True,
                message="Successfully logged out",
            )
        else:
            return LogoutResponse(
                success=False,
                message="Failed to revoke token (may already be revoked)",
            )

    return LogoutResponse(
        success=True,
        message="Logged out (no token provided to revoke)",
    )
