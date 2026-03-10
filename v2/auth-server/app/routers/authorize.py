"""
Authorization Router - Handles permission checks against OPA.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user, TokenData
from app.models.schemas import AuthorizeRequest, AuthorizeResponse
from app.services import opa_service


router = APIRouter(
    prefix="/api/v1",
    tags=["Authorization"],
)


@router.post(
    "/authorize",
    response_model=AuthorizeResponse,
    summary="Check Authorization",
    description="Check if the authenticated user is authorized to perform an action on a resource.",
)
async def authorize(
    request: AuthorizeRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """
    Check if the current user is authorized to perform an action.

    This endpoint requires a valid JWT access token.

    1. Validates the JWT token
    2. Queries OPA for authorization decision
    3. Returns authorization result with user context

    The `context` field in the request can contain additional data
    for fine-grained authorization (e.g., project_id, bu_id).
    """
    # Query OPA for authorization decision
    auth_response = await opa_service.get_authorization_response(
        email=current_user.email,
        platform=current_user.platform,
        resource=request.resource,
        action=request.action,
    )

    return AuthorizeResponse(
        allowed=auth_response.get("allowed", False),
        user_id=auth_response.get("user_id"),
        organization=auth_response.get("organization"),
        role=auth_response.get("role"),
        is_org_admin=auth_response.get("is_org_admin", 0),
    )


@router.get(
    "/authorize/me",
    summary="Get Current User Info",
    description="Get information about the currently authenticated user from JWT.",
)
async def get_me(current_user: TokenData = Depends(get_current_user)):
    """
    Get current user information from JWT token.

    Returns the decoded token claims for the authenticated user.
    """
    return {
        "email": current_user.email,
        "user_id": current_user.user_id,
        "organization": current_user.organization,
        "platform": current_user.platform,
        "is_org_admin": current_user.is_org_admin,
        "permissions": current_user.permissions,
    }


@router.post(
    "/authorize/batch",
    summary="Batch Authorization Check",
    description="Check multiple authorization decisions in a single request.",
)
async def authorize_batch(
    requests: list[AuthorizeRequest],
    current_user: TokenData = Depends(get_current_user),
):
    """
    Check multiple authorization decisions at once.

    Useful for UI components that need to know multiple permissions
    to render correctly (e.g., showing/hiding buttons).
    """
    results = []

    for req in requests:
        allowed = await opa_service.check_authorization(
            email=current_user.email,
            platform=current_user.platform,
            resource=req.resource,
            action=req.action,
        )
        results.append(
            {
                "resource": req.resource,
                "action": req.action,
                "allowed": allowed,
            }
        )

    return {
        "user_id": current_user.user_id,
        "organization": current_user.organization,
        "results": results,
    }
