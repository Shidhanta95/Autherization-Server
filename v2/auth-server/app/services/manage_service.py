"""
Management Service — CRUD operations for orgs, roles, permissions, and users.

All queries use asyncpg parameterized queries. Table names are resolved from the
platforms registry (never from user input) so they are safe for format strings.
Every mutating operation writes an audit_log entry in the same transaction.
"""

import json
from typing import Optional
from uuid import UUID

import asyncpg

from app.db import get_pool


# ============================================================
# HELPERS
# ============================================================


async def _get_prefix(conn: asyncpg.Connection, platform: str) -> str:
    """Resolve platform name to its table prefix. Raises ValueError if unknown."""
    row = await conn.fetchrow(
        "SELECT prefix FROM platforms WHERE name = $1 OR prefix = $1",
        platform,
    )
    if not row:
        raise ValueError(f"Unknown platform: {platform}")
    return row["prefix"]


async def _audit(
    conn: asyncpg.Connection,
    *,
    actor_email: str,
    platform: str,
    org_name: Optional[str],
    action: str,
    target_type: str,
    target_id: Optional[UUID],
    details: Optional[dict],
) -> None:
    """Insert an audit log entry."""
    await conn.execute(
        """
        INSERT INTO audit_log (actor_email, platform, org_name, action, target_type, target_id, details)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        """,
        actor_email,
        platform,
        org_name,
        action,
        target_type,
        target_id,
        json.dumps(details) if details else None,
    )


# ============================================================
# ORGANIZATIONS
# ============================================================


async def list_orgs(platform: str) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        rows = await conn.fetch(f"SELECT id, name FROM {pfx}_orgs ORDER BY name")
        orgs = [dict(r) for r in rows]
        return {"orgs": orgs, "total": len(orgs)}


async def get_org(platform: str, org_id: UUID) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        row = await conn.fetchrow(
            f"SELECT id, name FROM {pfx}_orgs WHERE id = $1", org_id
        )
        return dict(row) if row else None


async def create_org(platform: str, name: str, actor_email: str) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            row = await conn.fetchrow(
                f"INSERT INTO {pfx}_orgs (name) VALUES ($1) RETURNING id, name",
                name,
            )
            await _audit(
                conn,
                actor_email=actor_email,
                platform=platform,
                org_name=name,
                action="create_org",
                target_type="org",
                target_id=row["id"],
                details={"name": name},
            )
            return dict(row)


async def update_org(
    platform: str, org_id: UUID, name: str, actor_email: str
) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            row = await conn.fetchrow(
                f"UPDATE {pfx}_orgs SET name = $1 WHERE id = $2 RETURNING id, name",
                name,
                org_id,
            )
            if not row:
                return None
            await _audit(
                conn,
                actor_email=actor_email,
                platform=platform,
                org_name=name,
                action="update_org",
                target_type="org",
                target_id=org_id,
                details={"name": name},
            )
            return dict(row)


async def delete_org(platform: str, org_id: UUID, actor_email: str) -> bool:
    """Delete org. Returns False if org has roles (409 scenario)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            # Check for dependent roles
            count = await conn.fetchval(
                f"SELECT count(*) FROM {pfx}_roles WHERE org_id = $1", org_id
            )
            if count > 0:
                return False

            org = await conn.fetchrow(
                f"SELECT name FROM {pfx}_orgs WHERE id = $1", org_id
            )
            deleted = await conn.fetchrow(
                f"DELETE FROM {pfx}_orgs WHERE id = $1 RETURNING id", org_id
            )
            if deleted:
                await _audit(
                    conn,
                    actor_email=actor_email,
                    platform=platform,
                    org_name=org["name"] if org else None,
                    action="delete_org",
                    target_type="org",
                    target_id=org_id,
                    details=None,
                )
                return True
            return False


# ============================================================
# ROLES
# ============================================================


async def list_roles(platform: str, org_id: UUID) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        rows = await conn.fetch(
            f"""
            SELECT r.id, r.name, r.global_access, r.bu_access, o.name AS org_name
            FROM {pfx}_roles r
            JOIN {pfx}_orgs o ON o.id = r.org_id
            WHERE r.org_id = $1
            ORDER BY r.name
            """,
            org_id,
        )
        roles = [dict(r) for r in rows]
        return {"roles": roles, "total": len(roles)}


async def get_role(platform: str, org_id: UUID, role_id: UUID) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        row = await conn.fetchrow(
            f"""
            SELECT r.id, r.name, r.global_access, r.bu_access, o.name AS org_name
            FROM {pfx}_roles r
            JOIN {pfx}_orgs o ON o.id = r.org_id
            WHERE r.id = $1 AND r.org_id = $2
            """,
            role_id,
            org_id,
        )
        if not row:
            return None

        perms = await conn.fetch(
            f"SELECT resource, can_read, can_write, can_delete FROM {pfx}_perms WHERE role_id = $1 ORDER BY resource",
            role_id,
        )
        result = dict(row)
        result["permissions"] = [dict(p) for p in perms]
        return result


async def create_role(
    platform: str, org_id: UUID, data: dict, actor_email: str
) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            # Verify org exists
            org = await conn.fetchrow(
                f"SELECT name FROM {pfx}_orgs WHERE id = $1", org_id
            )
            if not org:
                raise ValueError("Organization not found")

            row = await conn.fetchrow(
                f"""
                INSERT INTO {pfx}_roles (org_id, name, global_access, bu_access)
                VALUES ($1, $2, $3, $4)
                RETURNING id, name, global_access, bu_access
                """,
                org_id,
                data["name"],
                data.get("global_access", False),
                data.get("bu_access", False),
            )
            result = dict(row)
            result["org_name"] = org["name"]

            await _audit(
                conn,
                actor_email=actor_email,
                platform=platform,
                org_name=org["name"],
                action="create_role",
                target_type="role",
                target_id=row["id"],
                details=data,
            )
            return result


async def update_role(
    platform: str, org_id: UUID, role_id: UUID, data: dict, actor_email: str
) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            existing = await conn.fetchrow(
                f"""
                SELECT r.id, r.name, r.global_access, r.bu_access, o.name AS org_name
                FROM {pfx}_roles r JOIN {pfx}_orgs o ON o.id = r.org_id
                WHERE r.id = $1 AND r.org_id = $2
                """,
                role_id,
                org_id,
            )
            if not existing:
                return None

            name = data.get("name", existing["name"])
            global_access = data.get("global_access", existing["global_access"])
            bu_access = data.get("bu_access", existing["bu_access"])

            row = await conn.fetchrow(
                f"""
                UPDATE {pfx}_roles
                SET name = $1, global_access = $2, bu_access = $3
                WHERE id = $4
                RETURNING id, name, global_access, bu_access
                """,
                name,
                global_access,
                bu_access,
                role_id,
            )
            result = dict(row)
            result["org_name"] = existing["org_name"]

            await _audit(
                conn,
                actor_email=actor_email,
                platform=platform,
                org_name=existing["org_name"],
                action="update_role",
                target_type="role",
                target_id=role_id,
                details=data,
            )
            return result


async def delete_role(
    platform: str, org_id: UUID, role_id: UUID, actor_email: str
) -> bool:
    """Delete role. Returns False if role has users (409 scenario)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            count = await conn.fetchval(
                f"SELECT count(*) FROM {pfx}_users WHERE role_id = $1", role_id
            )
            if count > 0:
                return False

            role = await conn.fetchrow(
                f"""
                SELECT r.name, o.name AS org_name
                FROM {pfx}_roles r JOIN {pfx}_orgs o ON o.id = r.org_id
                WHERE r.id = $1 AND r.org_id = $2
                """,
                role_id,
                org_id,
            )
            deleted = await conn.fetchrow(
                f"DELETE FROM {pfx}_roles WHERE id = $1 AND org_id = $2 RETURNING id",
                role_id,
                org_id,
            )
            if deleted:
                await _audit(
                    conn,
                    actor_email=actor_email,
                    platform=platform,
                    org_name=role["org_name"] if role else None,
                    action="delete_role",
                    target_type="role",
                    target_id=role_id,
                    details={"role_name": role["name"]} if role else None,
                )
                return True
            return False


# ============================================================
# PERMISSIONS
# ============================================================


async def get_permissions(platform: str, org_id: UUID, role_id: UUID) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        role = await conn.fetchrow(
            f"""
            SELECT r.name AS role_name, o.name AS org_name
            FROM {pfx}_roles r JOIN {pfx}_orgs o ON o.id = r.org_id
            WHERE r.id = $1 AND r.org_id = $2
            """,
            role_id,
            org_id,
        )
        if not role:
            return None

        rows = await conn.fetch(
            f"SELECT resource, can_read, can_write, can_delete FROM {pfx}_perms WHERE role_id = $1 ORDER BY resource",
            role_id,
        )
        perms = [dict(r) for r in rows]
        return {
            "role_name": role["role_name"],
            "org_name": role["org_name"],
            "permissions": perms,
            "total": len(perms),
        }


async def set_permissions(
    platform: str,
    org_id: UUID,
    role_id: UUID,
    permissions: list[dict],
    actor_email: str,
) -> dict:
    """Bulk upsert permissions for a role."""
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            role = await conn.fetchrow(
                f"""
                SELECT r.name AS role_name, o.name AS org_name
                FROM {pfx}_roles r JOIN {pfx}_orgs o ON o.id = r.org_id
                WHERE r.id = $1 AND r.org_id = $2
                """,
                role_id,
                org_id,
            )
            if not role:
                raise ValueError("Role not found in this organization")

            for perm in permissions:
                await conn.execute(
                    f"""
                    INSERT INTO {pfx}_perms (role_id, resource, can_read, can_write, can_delete)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (role_id, resource) DO UPDATE
                    SET can_read = $3, can_write = $4, can_delete = $5
                    """,
                    role_id,
                    perm["resource"],
                    perm.get("can_read", False),
                    perm.get("can_write", False),
                    perm.get("can_delete", False),
                )

            await _audit(
                conn,
                actor_email=actor_email,
                platform=platform,
                org_name=role["org_name"],
                action="set_permissions",
                target_type="permission",
                target_id=role_id,
                details={
                    "role_name": role["role_name"],
                    "permissions": permissions,
                },
            )

            # Return updated permissions
            rows = await conn.fetch(
                f"SELECT resource, can_read, can_write, can_delete FROM {pfx}_perms WHERE role_id = $1 ORDER BY resource",
                role_id,
            )
            perms = [dict(r) for r in rows]
            return {
                "role_name": role["role_name"],
                "org_name": role["org_name"],
                "permissions": perms,
                "total": len(perms),
            }


async def delete_permission(
    platform: str,
    org_id: UUID,
    role_id: UUID,
    resource: str,
    actor_email: str,
) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            role = await conn.fetchrow(
                f"""
                SELECT r.name AS role_name, o.name AS org_name
                FROM {pfx}_roles r JOIN {pfx}_orgs o ON o.id = r.org_id
                WHERE r.id = $1 AND r.org_id = $2
                """,
                role_id,
                org_id,
            )
            if not role:
                return False

            deleted = await conn.fetchrow(
                f"DELETE FROM {pfx}_perms WHERE role_id = $1 AND resource = $2 RETURNING role_id",
                role_id,
                resource,
            )
            if deleted:
                await _audit(
                    conn,
                    actor_email=actor_email,
                    platform=platform,
                    org_name=role["org_name"],
                    action="delete_permission",
                    target_type="permission",
                    target_id=role_id,
                    details={
                        "role_name": role["role_name"],
                        "resource": resource,
                    },
                )
                return True
            return False


# ============================================================
# USERS
# ============================================================


async def list_users(platform: str, org_id: UUID) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        rows = await conn.fetch(
            f"""
            SELECT u.id, u.email, u.user_uid, r.name AS role_name,
                   o.name AS org_name, u.is_org_admin
            FROM {pfx}_users u
            JOIN {pfx}_roles r ON r.id = u.role_id
            JOIN {pfx}_orgs o ON o.id = u.org_id
            WHERE u.org_id = $1
            ORDER BY u.email
            """,
            org_id,
        )
        users = [dict(r) for r in rows]
        return {"users": users, "total": len(users)}


async def get_user(platform: str, org_id: UUID, user_id: UUID) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        row = await conn.fetchrow(
            f"""
            SELECT u.id, u.email, u.user_uid, r.name AS role_name,
                   o.name AS org_name, u.is_org_admin
            FROM {pfx}_users u
            JOIN {pfx}_roles r ON r.id = u.role_id
            JOIN {pfx}_orgs o ON o.id = u.org_id
            WHERE u.id = $1 AND u.org_id = $2
            """,
            user_id,
            org_id,
        )
        return dict(row) if row else None


async def add_user(
    platform: str, org_id: UUID, data: dict, actor_email: str
) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            org = await conn.fetchrow(
                f"SELECT name FROM {pfx}_orgs WHERE id = $1", org_id
            )
            if not org:
                raise ValueError("Organization not found")

            role = await conn.fetchrow(
                f"SELECT id FROM {pfx}_roles WHERE org_id = $1 AND name = $2",
                org_id,
                data["role_name"],
            )
            if not role:
                raise ValueError(
                    f"Role '{data['role_name']}' not found in this organization"
                )

            row = await conn.fetchrow(
                f"""
                INSERT INTO {pfx}_users (email, org_id, role_id, user_uid, is_org_admin)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, email, user_uid, is_org_admin
                """,
                data["email"],
                org_id,
                role["id"],
                data["user_uid"],
                data.get("is_org_admin", False),
            )
            result = dict(row)
            result["role_name"] = data["role_name"]
            result["org_name"] = org["name"]

            await _audit(
                conn,
                actor_email=actor_email,
                platform=platform,
                org_name=org["name"],
                action="add_user",
                target_type="user",
                target_id=row["id"],
                details={
                    "email": data["email"],
                    "role_name": data["role_name"],
                    "is_org_admin": data.get("is_org_admin", False),
                },
            )
            return result


async def update_user(
    platform: str, org_id: UUID, user_id: UUID, data: dict, actor_email: str
) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            existing = await conn.fetchrow(
                f"""
                SELECT u.id, u.email, u.user_uid, u.role_id, u.is_org_admin,
                       r.name AS role_name, o.name AS org_name
                FROM {pfx}_users u
                JOIN {pfx}_roles r ON r.id = u.role_id
                JOIN {pfx}_orgs o ON o.id = u.org_id
                WHERE u.id = $1 AND u.org_id = $2
                """,
                user_id,
                org_id,
            )
            if not existing:
                return None

            role_id = existing["role_id"]
            new_role_name = existing["role_name"]
            is_org_admin = existing["is_org_admin"]

            if data.get("role_name") is not None:
                role = await conn.fetchrow(
                    f"SELECT id, name FROM {pfx}_roles WHERE org_id = $1 AND name = $2",
                    org_id,
                    data["role_name"],
                )
                if not role:
                    raise ValueError(
                        f"Role '{data['role_name']}' not found in this organization"
                    )
                role_id = role["id"]
                new_role_name = role["name"]

            if data.get("is_org_admin") is not None:
                is_org_admin = data["is_org_admin"]

            row = await conn.fetchrow(
                f"""
                UPDATE {pfx}_users
                SET role_id = $1, is_org_admin = $2
                WHERE id = $3
                RETURNING id, email, user_uid, is_org_admin
                """,
                role_id,
                is_org_admin,
                user_id,
            )
            result = dict(row)
            result["role_name"] = new_role_name
            result["org_name"] = existing["org_name"]

            await _audit(
                conn,
                actor_email=actor_email,
                platform=platform,
                org_name=existing["org_name"],
                action="update_user",
                target_type="user",
                target_id=user_id,
                details=data,
            )
            return result


async def remove_user(
    platform: str, org_id: UUID, user_id: UUID, actor_email: str
) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        pfx = await _get_prefix(conn, platform)
        async with conn.transaction():
            user = await conn.fetchrow(
                f"""
                SELECT u.email, o.name AS org_name
                FROM {pfx}_users u JOIN {pfx}_orgs o ON o.id = u.org_id
                WHERE u.id = $1 AND u.org_id = $2
                """,
                user_id,
                org_id,
            )
            deleted = await conn.fetchrow(
                f"DELETE FROM {pfx}_users WHERE id = $1 AND org_id = $2 RETURNING id",
                user_id,
                org_id,
            )
            if deleted:
                await _audit(
                    conn,
                    actor_email=actor_email,
                    platform=platform,
                    org_name=user["org_name"] if user else None,
                    action="remove_user",
                    target_type="user",
                    target_id=user_id,
                    details={"email": user["email"]} if user else None,
                )
                return True
            return False


# ============================================================
# AUDIT LOG
# ============================================================


async def get_audit_log(
    platform: str,
    org_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        if org_name:
            rows = await conn.fetch(
                """
                SELECT id, timestamp, actor_email, platform, org_name,
                       action, target_type, target_id, details
                FROM audit_log
                WHERE platform = $1 AND org_name = $2
                ORDER BY timestamp DESC
                LIMIT $3 OFFSET $4
                """,
                platform,
                org_name,
                limit,
                offset,
            )
            total = await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE platform = $1 AND org_name = $2",
                platform,
                org_name,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, timestamp, actor_email, platform, org_name,
                       action, target_type, target_id, details
                FROM audit_log
                WHERE platform = $1
                ORDER BY timestamp DESC
                LIMIT $3 OFFSET $4
                """,
                platform,
                limit,
                offset,
            )
            total = await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE platform = $1",
                platform,
            )

        entries = []
        for r in rows:
            entry = dict(r)
            # asyncpg returns jsonb as str, parse it
            if isinstance(entry.get("details"), str):
                entry["details"] = json.loads(entry["details"])
            entries.append(entry)

        return {"entries": entries, "total": total}
