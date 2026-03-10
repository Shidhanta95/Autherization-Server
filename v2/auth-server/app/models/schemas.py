"""
Pydantic schemas for request/response models.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr


# ============================================================
# AUTH SCHEMAS
# ============================================================


class LoginRequest(BaseModel):
    """Request body for /login endpoint"""

    platform: str
    org_name: str

    class Config:
        json_schema_extra = {
            "example": {"platform": "mlops", "org_name": "cloudangles"}
        }


class TestLoginRequest(BaseModel):
    """Request body for /test-login endpoint (development only)"""

    platform: str
    org_name: str
    email: str  # Email is required for test login

    class Config:
        json_schema_extra = {
            "example": {
                "platform": "mlops",
                "org_name": "acme",
                "email": "testuser@acme.com",
            }
        }


class LoginResponse(BaseModel):
    """Response from /login endpoint"""

    login_url: str

    class Config:
        json_schema_extra = {
            "example": {
                "login_url": "https://dev-123456.okta.com/oauth2/v1/authorize?..."
            }
        }


class TokenResponse(BaseModel):
    """Response containing access and refresh tokens"""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        }


class CallbackResponse(BaseModel):
    """Full response from /callback endpoint"""

    success: bool
    email: str
    organization: str
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "email": "user@example.com",
                "organization": "cloudangles",
                "user_id": "uuid-123",
                "access_token": "eyJ...",
                "refresh_token": "eyJ...",
                "token_type": "Bearer",
                "expires_in": 3600,
                "message": "Successfully logged in via SSO",
            }
        }


class RefreshRequest(BaseModel):
    """Request body for /refresh endpoint"""

    refresh_token: str

    class Config:
        json_schema_extra = {
            "example": {"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}
        }


class LogoutRequest(BaseModel):
    """Request body for /logout endpoint"""

    refresh_token: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}
        }


class LogoutResponse(BaseModel):
    """Response from /logout endpoint"""

    success: bool
    message: str


# ============================================================
# AUTHORIZATION SCHEMAS
# ============================================================


class AuthorizeRequest(BaseModel):
    """Request body for /authorize endpoint"""

    resource: str
    action: str
    context: Optional[Dict[str, Any]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "resource": "projects",
                "action": "write",
                "context": {"project_id": "uuid-123", "bu_id": "uuid-456"},
            }
        }


class AuthorizeResponse(BaseModel):
    """Response from /authorize endpoint"""

    allowed: bool
    user_id: Optional[str] = None
    organization: Optional[str] = None
    role: Optional[str] = None
    is_org_admin: int = 0

    class Config:
        json_schema_extra = {
            "example": {
                "allowed": True,
                "user_id": "uuid-123",
                "organization": "cloudangles",
                "role": "admin",
                "is_org_admin": 1,
            }
        }


# ============================================================
# ERROR SCHEMAS
# ============================================================


class ErrorResponse(BaseModel):
    """Standard error response"""

    detail: str

    class Config:
        json_schema_extra = {"example": {"detail": "User not registered in system"}}


# ============================================================
# USER SCHEMAS
# ============================================================


class UserInfo(BaseModel):
    """User information from JWT"""

    email: str
    user_id: str
    organization: str
    platform: str
    is_org_admin: int
    permissions: Dict[str, Any]
