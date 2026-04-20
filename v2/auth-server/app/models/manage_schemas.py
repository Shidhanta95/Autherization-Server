"""
Pydantic schemas for the Management API (orgs, roles, permissions, users, audit).
"""

from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ============================================================
# ORGANIZATION SCHEMAS
# ============================================================


class OrgCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)

    class Config:
        json_schema_extra = {"example": {"name": "acme"}}


class OrgUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class OrgResponse(BaseModel):
    id: UUID
    name: str


class OrgListResponse(BaseModel):
    orgs: list[OrgResponse]
    total: int


# ============================================================
# ROLE SCHEMAS
# ============================================================


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    global_access: bool = False
    bu_access: bool = False

    class Config:
        json_schema_extra = {
            "example": {
                "name": "editor",
                "global_access": False,
                "bu_access": True,
            }
        }


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    global_access: Optional[bool] = None
    bu_access: Optional[bool] = None


class RoleResponse(BaseModel):
    id: UUID
    name: str
    global_access: bool
    bu_access: bool
    org_name: str


class PermissionItem(BaseModel):
    resource: str = Field(..., min_length=1, max_length=50)
    can_read: bool = False
    can_write: bool = False
    can_delete: bool = False


class RoleDetailResponse(BaseModel):
    id: UUID
    name: str
    global_access: bool
    bu_access: bool
    org_name: str
    permissions: list[PermissionItem]


class RoleListResponse(BaseModel):
    roles: list[RoleResponse]
    total: int


# ============================================================
# PERMISSION SCHEMAS
# ============================================================


class PermissionSet(BaseModel):
    resource: str = Field(..., min_length=1, max_length=50)
    can_read: bool = False
    can_write: bool = False
    can_delete: bool = False

    class Config:
        json_schema_extra = {
            "example": {
                "resource": "projects",
                "can_read": True,
                "can_write": True,
                "can_delete": False,
            }
        }


class BulkPermissionSet(BaseModel):
    permissions: list[PermissionSet] = Field(..., min_length=1)

    class Config:
        json_schema_extra = {
            "example": {
                "permissions": [
                    {
                        "resource": "projects",
                        "can_read": True,
                        "can_write": True,
                        "can_delete": False,
                    },
                    {
                        "resource": "pipelines",
                        "can_read": True,
                        "can_write": False,
                        "can_delete": False,
                    },
                ]
            }
        }


class PermissionResponse(BaseModel):
    resource: str
    can_read: bool
    can_write: bool
    can_delete: bool


class PermissionListResponse(BaseModel):
    role_name: str
    org_name: str
    permissions: list[PermissionResponse]
    total: int


# ============================================================
# USER SCHEMAS
# ============================================================


class UserAdd(BaseModel):
    email: EmailStr
    role_name: str = Field(..., min_length=1, max_length=100)
    user_uid: str = Field(..., min_length=1, max_length=255)
    is_org_admin: bool = False

    class Config:
        json_schema_extra = {
            "example": {
                "email": "jane@acme.com",
                "role_name": "editor",
                "user_uid": "okta-uid-12345",
                "is_org_admin": False,
            }
        }


class UserUpdate(BaseModel):
    role_name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_org_admin: Optional[bool] = None


class UserResponse(BaseModel):
    id: UUID
    email: str
    user_uid: str
    role_name: str
    org_name: str
    is_org_admin: bool


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


# ============================================================
# AUDIT SCHEMAS
# ============================================================


class AuditEntry(BaseModel):
    id: UUID
    timestamp: datetime
    actor_email: str
    platform: str
    org_name: Optional[str]
    action: str
    target_type: str
    target_id: Optional[UUID]
    details: Optional[dict[str, Any]]


class AuditListResponse(BaseModel):
    entries: list[AuditEntry]
    total: int
