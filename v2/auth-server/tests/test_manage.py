"""
Tests for Management API endpoints.

All management endpoints require org admin privileges (is_org_admin=1 in JWT).
The database layer (manage_service) is mocked — these tests verify routing,
authentication, authorization, request validation, and response shaping.
"""

import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient


SAMPLE_ORG_ID = str(uuid4())
SAMPLE_ROLE_ID = str(uuid4())
SAMPLE_USER_ID = str(uuid4())


# ============================================================
# ORGANIZATIONS
# ============================================================


class TestListOrgs:
    """Tests for GET /api/v1/manage/orgs"""

    def test_list_orgs_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "orgs": [{"id": SAMPLE_ORG_ID, "name": "acme"}],
            "total": 1,
        }
        with patch("app.routers.manage.manage_service.list_orgs", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                "/api/v1/manage/orgs",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["orgs"][0]["name"] == "acme"

    def test_list_orgs_non_admin_rejected(self, client: TestClient, non_admin_access_token):
        response = client.get(
            "/api/v1/manage/orgs",
            headers={"Authorization": f"Bearer {non_admin_access_token}"},
        )
        assert response.status_code == 403
        assert "org admin" in response.json()["detail"].lower()

    def test_list_orgs_no_token(self, client: TestClient):
        response = client.get("/api/v1/manage/orgs")
        assert response.status_code == 403


class TestCreateOrg:
    """Tests for POST /api/v1/manage/orgs"""

    def test_create_org_success(self, client: TestClient, valid_access_token):
        mock_result = {"id": SAMPLE_ORG_ID, "name": "newcorp"}
        with patch("app.routers.manage.manage_service.create_org", new_callable=AsyncMock, return_value=mock_result):
            response = client.post(
                "/api/v1/manage/orgs",
                json={"name": "newcorp"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 201
        assert response.json()["name"] == "newcorp"

    def test_create_org_duplicate(self, client: TestClient, valid_access_token):
        with patch(
            "app.routers.manage.manage_service.create_org",
            new_callable=AsyncMock,
            side_effect=Exception("unique constraint violation: duplicate key"),
        ):
            response = client.post(
                "/api/v1/manage/orgs",
                json={"name": "existing"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_create_org_missing_name(self, client: TestClient, valid_access_token):
        response = client.post(
            "/api/v1/manage/orgs",
            json={},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        assert response.status_code == 422


class TestGetOrg:
    """Tests for GET /api/v1/manage/orgs/{org_id}"""

    def test_get_org_success(self, client: TestClient, valid_access_token):
        mock_result = {"id": SAMPLE_ORG_ID, "name": "acme"}
        with patch("app.routers.manage.manage_service.get_org", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["name"] == "acme"

    def test_get_org_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.get_org", new_callable=AsyncMock, return_value=None):
            response = client.get(
                f"/api/v1/manage/orgs/{uuid4()}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


class TestUpdateOrg:
    """Tests for PUT /api/v1/manage/orgs/{org_id}"""

    def test_update_org_success(self, client: TestClient, valid_access_token):
        mock_result = {"id": SAMPLE_ORG_ID, "name": "newname"}
        with patch("app.routers.manage.manage_service.update_org", new_callable=AsyncMock, return_value=mock_result):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}",
                json={"name": "newname"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["name"] == "newname"

    def test_update_org_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.update_org", new_callable=AsyncMock, return_value=None):
            response = client.put(
                f"/api/v1/manage/orgs/{uuid4()}",
                json={"name": "x"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404

    def test_update_org_duplicate_name(self, client: TestClient, valid_access_token):
        with patch(
            "app.routers.manage.manage_service.update_org",
            new_callable=AsyncMock,
            side_effect=Exception("unique constraint: duplicate"),
        ):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}",
                json={"name": "taken"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 409


class TestDeleteOrg:
    """Tests for DELETE /api/v1/manage/orgs/{org_id}"""

    def test_delete_org_success(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.delete_org", new_callable=AsyncMock, return_value=True):
            response = client.delete(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 204

    def test_delete_org_has_roles(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.delete_org", new_callable=AsyncMock, return_value=False):
            response = client.delete(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 409
        assert "roles" in response.json()["detail"].lower()


# ============================================================
# ROLES
# ============================================================


class TestListRoles:
    """Tests for GET /api/v1/manage/orgs/{org_id}/roles"""

    def test_list_roles_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "roles": [
                {"id": SAMPLE_ROLE_ID, "name": "admin", "global_access": True, "bu_access": False, "org_name": "acme"},
            ],
            "total": 1,
        }
        with patch("app.routers.manage.manage_service.list_roles", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["total"] == 1


class TestCreateRole:
    """Tests for POST /api/v1/manage/orgs/{org_id}/roles"""

    def test_create_role_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "id": SAMPLE_ROLE_ID,
            "name": "editor",
            "global_access": False,
            "bu_access": True,
            "org_name": "acme",
        }
        with patch("app.routers.manage.manage_service.create_role", new_callable=AsyncMock, return_value=mock_result):
            response = client.post(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles",
                json={"name": "editor", "global_access": False, "bu_access": True},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 201
        assert response.json()["name"] == "editor"
        assert response.json()["bu_access"] is True

    def test_create_role_duplicate(self, client: TestClient, valid_access_token):
        with patch(
            "app.routers.manage.manage_service.create_role",
            new_callable=AsyncMock,
            side_effect=Exception("unique constraint: duplicate key"),
        ):
            response = client.post(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles",
                json={"name": "admin"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 409

    def test_create_role_org_not_found(self, client: TestClient, valid_access_token):
        with patch(
            "app.routers.manage.manage_service.create_role",
            new_callable=AsyncMock,
            side_effect=ValueError("Organization not found"),
        ):
            response = client.post(
                f"/api/v1/manage/orgs/{uuid4()}/roles",
                json={"name": "viewer"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


class TestGetRole:
    """Tests for GET /api/v1/manage/orgs/{org_id}/roles/{role_id}"""

    def test_get_role_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "id": SAMPLE_ROLE_ID,
            "name": "admin",
            "global_access": True,
            "bu_access": False,
            "org_name": "acme",
            "permissions": [
                {"resource": "projects", "can_read": True, "can_write": True, "can_delete": True},
            ],
        }
        with patch("app.routers.manage.manage_service.get_role", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "admin"
        assert len(data["permissions"]) == 1

    def test_get_role_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.get_role", new_callable=AsyncMock, return_value=None):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{uuid4()}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


class TestUpdateRole:
    """Tests for PUT /api/v1/manage/orgs/{org_id}/roles/{role_id}"""

    def test_update_role_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "id": SAMPLE_ROLE_ID,
            "name": "senior-editor",
            "global_access": True,
            "bu_access": False,
            "org_name": "acme",
        }
        with patch("app.routers.manage.manage_service.update_role", new_callable=AsyncMock, return_value=mock_result):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}",
                json={"name": "senior-editor", "global_access": True},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["name"] == "senior-editor"

    def test_update_role_empty_body(self, client: TestClient, valid_access_token):
        response = client.put(
            f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}",
            json={},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        assert response.status_code == 400
        assert "No fields to update" in response.json()["detail"]

    def test_update_role_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.update_role", new_callable=AsyncMock, return_value=None):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{uuid4()}",
                json={"name": "x"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


class TestDeleteRole:
    """Tests for DELETE /api/v1/manage/orgs/{org_id}/roles/{role_id}"""

    def test_delete_role_success(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.delete_role", new_callable=AsyncMock, return_value=True):
            response = client.delete(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 204

    def test_delete_role_has_users(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.delete_role", new_callable=AsyncMock, return_value=False):
            response = client.delete(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 409
        assert "users" in response.json()["detail"].lower()


# ============================================================
# PERMISSIONS
# ============================================================


class TestGetPermissions:
    """Tests for GET /api/v1/manage/orgs/{org_id}/roles/{role_id}/permissions"""

    def test_get_permissions_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "role_name": "editor",
            "org_name": "acme",
            "permissions": [
                {"resource": "projects", "can_read": True, "can_write": True, "can_delete": False},
            ],
            "total": 1,
        }
        with patch("app.routers.manage.manage_service.get_permissions", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}/permissions",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["role_name"] == "editor"
        assert data["org_name"] == "acme"
        assert data["total"] == 1

    def test_get_permissions_role_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.get_permissions", new_callable=AsyncMock, return_value=None):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{uuid4()}/permissions",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


class TestSetPermissions:
    """Tests for PUT /api/v1/manage/orgs/{org_id}/roles/{role_id}/permissions"""

    def test_set_permissions_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "role_name": "editor",
            "org_name": "acme",
            "permissions": [
                {"resource": "pipelines", "can_read": True, "can_write": False, "can_delete": False},
                {"resource": "projects", "can_read": True, "can_write": True, "can_delete": False},
            ],
            "total": 2,
        }
        with patch("app.routers.manage.manage_service.set_permissions", new_callable=AsyncMock, return_value=mock_result):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}/permissions",
                json={
                    "permissions": [
                        {"resource": "projects", "can_read": True, "can_write": True, "can_delete": False},
                        {"resource": "pipelines", "can_read": True, "can_write": False, "can_delete": False},
                    ]
                },
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_set_permissions_role_not_found(self, client: TestClient, valid_access_token):
        with patch(
            "app.routers.manage.manage_service.set_permissions",
            new_callable=AsyncMock,
            side_effect=ValueError("Role not found in this organization"),
        ):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{uuid4()}/permissions",
                json={"permissions": [{"resource": "x", "can_read": True}]},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404

    def test_set_permissions_empty_list(self, client: TestClient, valid_access_token):
        response = client.put(
            f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}/permissions",
            json={"permissions": []},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        assert response.status_code == 422


class TestDeletePermission:
    """Tests for DELETE /api/v1/manage/orgs/{org_id}/roles/{role_id}/permissions/{resource}"""

    def test_delete_permission_success(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.delete_permission", new_callable=AsyncMock, return_value=True):
            response = client.delete(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}/permissions/pipelines",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 204

    def test_delete_permission_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.delete_permission", new_callable=AsyncMock, return_value=False):
            response = client.delete(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/roles/{SAMPLE_ROLE_ID}/permissions/nonexistent",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


# ============================================================
# USERS
# ============================================================


class TestListUsers:
    """Tests for GET /api/v1/manage/orgs/{org_id}/users"""

    def test_list_users_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "users": [
                {
                    "id": SAMPLE_USER_ID,
                    "email": "jane@acme.com",
                    "user_uid": "uid-123",
                    "role_name": "editor",
                    "org_name": "acme",
                    "is_org_admin": False,
                }
            ],
            "total": 1,
        }
        with patch("app.routers.manage.manage_service.list_users", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["users"][0]["email"] == "jane@acme.com"


class TestAddUser:
    """Tests for POST /api/v1/manage/orgs/{org_id}/users"""

    def test_add_user_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "id": SAMPLE_USER_ID,
            "email": "jane@acme.com",
            "user_uid": "uid-123",
            "role_name": "editor",
            "org_name": "acme",
            "is_org_admin": False,
        }
        with patch("app.routers.manage.manage_service.add_user", new_callable=AsyncMock, return_value=mock_result):
            response = client.post(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users",
                json={
                    "email": "jane@acme.com",
                    "role_name": "editor",
                    "user_uid": "uid-123",
                    "is_org_admin": False,
                },
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 201
        assert response.json()["email"] == "jane@acme.com"

    def test_add_user_duplicate_email(self, client: TestClient, valid_access_token):
        with patch(
            "app.routers.manage.manage_service.add_user",
            new_callable=AsyncMock,
            side_effect=Exception("unique constraint: duplicate key"),
        ):
            response = client.post(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users",
                json={
                    "email": "existing@acme.com",
                    "role_name": "editor",
                    "user_uid": "uid-dup",
                },
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 409

    def test_add_user_role_not_found(self, client: TestClient, valid_access_token):
        with patch(
            "app.routers.manage.manage_service.add_user",
            new_callable=AsyncMock,
            side_effect=ValueError("Role 'ghost' not found in this organization"),
        ):
            response = client.post(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users",
                json={
                    "email": "new@acme.com",
                    "role_name": "ghost",
                    "user_uid": "uid-new",
                },
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404

    def test_add_user_invalid_email(self, client: TestClient, valid_access_token):
        response = client.post(
            f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users",
            json={
                "email": "not-an-email",
                "role_name": "editor",
                "user_uid": "uid-bad",
            },
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        assert response.status_code == 422


class TestGetUser:
    """Tests for GET /api/v1/manage/orgs/{org_id}/users/{user_id}"""

    def test_get_user_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "id": SAMPLE_USER_ID,
            "email": "jane@acme.com",
            "user_uid": "uid-123",
            "role_name": "editor",
            "org_name": "acme",
            "is_org_admin": False,
        }
        with patch("app.routers.manage.manage_service.get_user", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users/{SAMPLE_USER_ID}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["email"] == "jane@acme.com"

    def test_get_user_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.get_user", new_callable=AsyncMock, return_value=None):
            response = client.get(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users/{uuid4()}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


class TestUpdateUser:
    """Tests for PUT /api/v1/manage/orgs/{org_id}/users/{user_id}"""

    def test_update_user_role(self, client: TestClient, valid_access_token):
        mock_result = {
            "id": SAMPLE_USER_ID,
            "email": "jane@acme.com",
            "user_uid": "uid-123",
            "role_name": "admin",
            "org_name": "acme",
            "is_org_admin": True,
        }
        with patch("app.routers.manage.manage_service.update_user", new_callable=AsyncMock, return_value=mock_result):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users/{SAMPLE_USER_ID}",
                json={"role_name": "admin", "is_org_admin": True},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["role_name"] == "admin"
        assert response.json()["is_org_admin"] is True

    def test_update_user_empty_body(self, client: TestClient, valid_access_token):
        response = client.put(
            f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users/{SAMPLE_USER_ID}",
            json={},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        assert response.status_code == 400
        assert "No fields" in response.json()["detail"]

    def test_update_user_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.update_user", new_callable=AsyncMock, return_value=None):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users/{uuid4()}",
                json={"role_name": "viewer"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404

    def test_update_user_role_not_found(self, client: TestClient, valid_access_token):
        with patch(
            "app.routers.manage.manage_service.update_user",
            new_callable=AsyncMock,
            side_effect=ValueError("Role 'ghost' not found"),
        ):
            response = client.put(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users/{SAMPLE_USER_ID}",
                json={"role_name": "ghost"},
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


class TestRemoveUser:
    """Tests for DELETE /api/v1/manage/orgs/{org_id}/users/{user_id}"""

    def test_remove_user_success(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.remove_user", new_callable=AsyncMock, return_value=True):
            response = client.delete(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users/{SAMPLE_USER_ID}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 204

    def test_remove_user_not_found(self, client: TestClient, valid_access_token):
        with patch("app.routers.manage.manage_service.remove_user", new_callable=AsyncMock, return_value=False):
            response = client.delete(
                f"/api/v1/manage/orgs/{SAMPLE_ORG_ID}/users/{uuid4()}",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 404


# ============================================================
# AUDIT LOG
# ============================================================


class TestAuditLog:
    """Tests for GET /api/v1/manage/audit"""

    def test_audit_log_success(self, client: TestClient, valid_access_token):
        mock_result = {
            "entries": [
                {
                    "id": str(uuid4()),
                    "timestamp": "2026-04-23T12:00:00",
                    "actor_email": "admin@acme.com",
                    "platform": "mlops",
                    "org_name": "acme",
                    "action": "create_role",
                    "target_type": "role",
                    "target_id": SAMPLE_ROLE_ID,
                    "details": {"name": "editor"},
                }
            ],
            "total": 1,
        }
        with patch("app.routers.manage.manage_service.get_audit_log", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                "/api/v1/manage/audit?org_name=acme&limit=10",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["entries"][0]["action"] == "create_role"

    def test_audit_log_no_filter(self, client: TestClient, valid_access_token):
        mock_result = {"entries": [], "total": 0}
        with patch("app.routers.manage.manage_service.get_audit_log", new_callable=AsyncMock, return_value=mock_result):
            response = client.get(
                "/api/v1/manage/audit",
                headers={"Authorization": f"Bearer {valid_access_token}"},
            )

        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_audit_log_non_admin_rejected(self, client: TestClient, non_admin_access_token):
        response = client.get(
            "/api/v1/manage/audit",
            headers={"Authorization": f"Bearer {non_admin_access_token}"},
        )
        assert response.status_code == 403
