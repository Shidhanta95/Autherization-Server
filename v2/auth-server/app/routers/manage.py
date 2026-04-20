"""
Management Router — CRUD endpoints for orgs, roles, permissions, and users.

All endpoints require org admin privileges (via require_org_admin dependency).
The platform is taken from the caller's JWT — users can only manage the platform
they are authenticated for.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import require_org_admin, TokenData
from app.models.manage_schemas import (
    OrgCreate,
    OrgUpdate,
    OrgResponse,
    OrgListResponse,
    RoleCreate,
    RoleUpdate,
    RoleResponse,
    RoleDetailResponse,
    RoleListResponse,
    BulkPermissionSet,
    PermissionListResponse,
    UserAdd,
    UserUpdate,
    UserResponse,
    UserListResponse,
    AuditListResponse,
)
from app.services import manage_service


router = APIRouter(
    prefix="/api/v1/manage",
    tags=["Management"],
)


# ============================================================
# ORGANIZATIONS
# ============================================================


@router.get(
    "/orgs",
    response_model=OrgListResponse,
    summary="List Organizations",
)
async def list_orgs(current_user: TokenData = Depends(require_org_admin)):
    """List all organizations for the caller's platform."""
    return await manage_service.list_orgs(current_user.platform)


@router.post(
    "/orgs",
    response_model=OrgResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Organization",
)
async def create_org(
    body: OrgCreate,
    current_user: TokenData = Depends(require_org_admin),
):
    """Create a new organization in the caller's platform."""
    try:
        return await manage_service.create_org(
            current_user.platform, body.name, current_user.email
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization '{body.name}' already exists",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get(
    "/orgs/{org_id}",
    response_model=OrgResponse,
    summary="Get Organization",
)
async def get_org(
    org_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    result = await manage_service.get_org(current_user.platform, org_id)
    if not result:
        raise HTTPException(status_code=404, detail="Organization not found")
    return result


@router.put(
    "/orgs/{org_id}",
    response_model=OrgResponse,
    summary="Update Organization",
)
async def update_org(
    org_id: UUID,
    body: OrgUpdate,
    current_user: TokenData = Depends(require_org_admin),
):
    try:
        result = await manage_service.update_org(
            current_user.platform, org_id, body.name, current_user.email
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization '{body.name}' already exists",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    if not result:
        raise HTTPException(status_code=404, detail="Organization not found")
    return result


@router.delete(
    "/orgs/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Organization",
)
async def delete_org(
    org_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    """Delete an organization. Fails with 409 if it still has roles."""
    deleted = await manage_service.delete_org(
        current_user.platform, org_id, current_user.email
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete organization that still has roles. Remove all roles first.",
        )


# ============================================================
# ROLES
# ============================================================


@router.get(
    "/orgs/{org_id}/roles",
    response_model=RoleListResponse,
    summary="List Roles",
)
async def list_roles(
    org_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    return await manage_service.list_roles(current_user.platform, org_id)


@router.post(
    "/orgs/{org_id}/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Role",
)
async def create_role(
    org_id: UUID,
    body: RoleCreate,
    current_user: TokenData = Depends(require_org_admin),
):
    try:
        return await manage_service.create_role(
            current_user.platform,
            org_id,
            body.model_dump(),
            current_user.email,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Role '{body.name}' already exists in this organization",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get(
    "/orgs/{org_id}/roles/{role_id}",
    response_model=RoleDetailResponse,
    summary="Get Role Details",
)
async def get_role(
    org_id: UUID,
    role_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    """Get role details including all permissions."""
    result = await manage_service.get_role(
        current_user.platform, org_id, role_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Role not found")
    return result


@router.put(
    "/orgs/{org_id}/roles/{role_id}",
    response_model=RoleResponse,
    summary="Update Role",
)
async def update_role(
    org_id: UUID,
    role_id: UUID,
    body: RoleUpdate,
    current_user: TokenData = Depends(require_org_admin),
):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    try:
        result = await manage_service.update_role(
            current_user.platform, org_id, role_id, data, current_user.email
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Role name '{body.name}' already exists in this organization",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    if not result:
        raise HTTPException(status_code=404, detail="Role not found")
    return result


@router.delete(
    "/orgs/{org_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Role",
)
async def delete_role(
    org_id: UUID,
    role_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    """Delete a role. Fails with 409 if it still has users assigned."""
    deleted = await manage_service.delete_role(
        current_user.platform, org_id, role_id, current_user.email
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete role that still has users. Reassign or remove all users first.",
        )


# ============================================================
# PERMISSIONS
# ============================================================


@router.get(
    "/orgs/{org_id}/roles/{role_id}/permissions",
    response_model=PermissionListResponse,
    summary="Get Permissions",
)
async def get_permissions(
    org_id: UUID,
    role_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    result = await manage_service.get_permissions(
        current_user.platform, org_id, role_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Role not found")
    return result


@router.put(
    "/orgs/{org_id}/roles/{role_id}/permissions",
    response_model=PermissionListResponse,
    summary="Set Permissions (bulk upsert)",
)
async def set_permissions(
    org_id: UUID,
    role_id: UUID,
    body: BulkPermissionSet,
    current_user: TokenData = Depends(require_org_admin),
):
    """Bulk set permissions for a role. Upserts — existing resources are updated, new ones created."""
    try:
        return await manage_service.set_permissions(
            current_user.platform,
            org_id,
            role_id,
            [p.model_dump() for p in body.permissions],
            current_user.email,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete(
    "/orgs/{org_id}/roles/{role_id}/permissions/{resource}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke Permission",
)
async def delete_permission(
    org_id: UUID,
    role_id: UUID,
    resource: str,
    current_user: TokenData = Depends(require_org_admin),
):
    """Revoke all permissions on a resource for a role."""
    deleted = await manage_service.delete_permission(
        current_user.platform, org_id, role_id, resource, current_user.email
    )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Permission not found for this role and resource",
        )


# ============================================================
# USERS
# ============================================================


@router.get(
    "/orgs/{org_id}/users",
    response_model=UserListResponse,
    summary="List Users",
)
async def list_users(
    org_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    return await manage_service.list_users(current_user.platform, org_id)


@router.post(
    "/orgs/{org_id}/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add User",
)
async def add_user(
    org_id: UUID,
    body: UserAdd,
    current_user: TokenData = Depends(require_org_admin),
):
    """Add a user to an organization with a specific role."""
    try:
        return await manage_service.add_user(
            current_user.platform, org_id, body.model_dump(), current_user.email
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User '{body.email}' already exists in this platform",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get(
    "/orgs/{org_id}/users/{user_id}",
    response_model=UserResponse,
    summary="Get User",
)
async def get_user(
    org_id: UUID,
    user_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    result = await manage_service.get_user(
        current_user.platform, org_id, user_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return result


@router.put(
    "/orgs/{org_id}/users/{user_id}",
    response_model=UserResponse,
    summary="Update User",
)
async def update_user(
    org_id: UUID,
    user_id: UUID,
    body: UserUpdate,
    current_user: TokenData = Depends(require_org_admin),
):
    """Update a user's role or org admin status."""
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    try:
        result = await manage_service.update_user(
            current_user.platform, org_id, user_id, data, current_user.email
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return result


@router.delete(
    "/orgs/{org_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove User",
)
async def remove_user(
    org_id: UUID,
    user_id: UUID,
    current_user: TokenData = Depends(require_org_admin),
):
    removed = await manage_service.remove_user(
        current_user.platform, org_id, user_id, current_user.email
    )
    if not removed:
        raise HTTPException(status_code=404, detail="User not found")


# ============================================================
# AUDIT LOG
# ============================================================


@router.get(
    "/audit",
    response_model=AuditListResponse,
    summary="Query Audit Log",
)
async def get_audit_log(
    org_name: str = Query(None, description="Filter by organization name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: TokenData = Depends(require_org_admin),
):
    """Query the audit log for the caller's platform."""
    return await manage_service.get_audit_log(
        current_user.platform, org_name=org_name, limit=limit, offset=offset
    )
