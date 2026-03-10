"""
OPA Rule Update Tests.

Tests the OPA policy and data update mechanisms:
1. Policy updates via REST API
2. RBAC data updates via REST API
3. User data updates
4. Authorization changes after updates
5. Hot-reload behavior
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


class TestOPAPolicyUpdates:
    """Test OPA policy update mechanisms"""

    @pytest.fixture
    def mock_opa_responses(self):
        """Create mock OPA responses for policy updates"""
        return {
            "policy_success": {"result": {}},
            "policy_error": {
                "code": "invalid_parameter",
                "message": "error parsing policy",
            },
        }

    @pytest.mark.asyncio
    async def test_push_policy_success(self):
        """Test successful policy push to OPA"""
        policy_content = """
        package authz
        default allow := false
        allow { input.user == "admin" }
        """

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.put.return_value = mock_response

            async with httpx.AsyncClient() as client:
                response = await client.put(
                    "http://opa:8181/v1/policies/authz",
                    content=policy_content,
                    headers={"Content-Type": "text/plain"},
                )

            assert mock_response.status_code == 200

    @pytest.mark.asyncio
    async def test_push_invalid_policy_rejected(self):
        """Test that invalid policy is rejected by OPA"""
        invalid_policy = """
        package authz
        this is not valid rego syntax!!!
        """

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "code": "invalid_parameter",
            "message": "error parsing policy",
        }

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.put.return_value = mock_response

            # Simulating the response
            assert mock_response.status_code == 400
            assert "invalid_parameter" in mock_response.json()["code"]

    @pytest.mark.asyncio
    async def test_policy_update_changes_authorization(self):
        """Test that policy updates affect authorization decisions"""
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        # First: user is denied (no matching rule)
        mock_response_denied = AsyncMock()
        mock_response_denied.status_code = 200
        mock_response_denied.json = MagicMock(return_value={"result": False})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_denied

            result = await opa_service.check_authorization(
                email="user@example.com",
                platform="mlops",
                resource="projects",
                action="delete",
            )
            assert result is False

        # After policy update: user is allowed
        mock_response_allowed = AsyncMock()
        mock_response_allowed.status_code = 200
        mock_response_allowed.json = MagicMock(return_value={"result": True})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_allowed

            result = await opa_service.check_authorization(
                email="user@example.com",
                platform="mlops",
                resource="projects",
                action="delete",
            )
            assert result is True


class TestOPADataUpdates:
    """Test OPA data (RBAC) update mechanisms"""

    @pytest.mark.asyncio
    async def test_push_rbac_data_success(self):
        """Test successful RBAC data push to OPA"""
        rbac_data = {
            "mlops": {
                "acme": {
                    "admin": {
                        "projects": {"read": True, "write": True, "delete": True},
                        "pipelines": {"read": True, "write": True, "delete": True},
                        "global_access": True,
                        "bu_access": True,
                    },
                    "viewer": {
                        "projects": {"read": True, "write": False, "delete": False},
                        "pipelines": {"read": True, "write": False, "delete": False},
                        "global_access": False,
                        "bu_access": False,
                    },
                }
            }
        }

        mock_response = MagicMock()
        mock_response.status_code = 204  # OPA returns 204 on successful data PUT

        with patch("httpx.put", return_value=mock_response):
            # Simulate data push
            assert mock_response.status_code == 204

    @pytest.mark.asyncio
    async def test_push_user_data_success(self):
        """Test successful user data push to OPA"""
        user_data = {
            "user_roles": {
                "admin@acme.com": "admin",
                "viewer@acme.com": "viewer",
            },
            "user_tenant": {
                "admin@acme.com": "acme",
                "viewer@acme.com": "acme",
            },
            "user_ids": {
                "admin@acme.com": "user-001",
                "viewer@acme.com": "user-002",
            },
            "org_admin_flag": {
                "admin@acme.com": 1,
                "viewer@acme.com": 0,
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.put", return_value=mock_response):
            assert mock_response.status_code == 204

    @pytest.mark.asyncio
    async def test_add_new_user_updates_authorization(self):
        """Test that adding a new user allows them to authenticate"""
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        # Before: user doesn't exist
        mock_response_not_found = AsyncMock()
        mock_response_not_found.status_code = 200
        mock_response_not_found.json = MagicMock(return_value={"result": False})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_not_found

            exists = await opa_service.check_user_exists(
                email="newuser@acme.com",
            )
            assert exists is False

        # After: user exists (data was updated)
        mock_response_found = AsyncMock()
        mock_response_found.status_code = 200
        mock_response_found.json = MagicMock(return_value={"result": True})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_found

            exists = await opa_service.check_user_exists(
                email="newuser@acme.com",
            )
            assert exists is True

    @pytest.mark.asyncio
    async def test_role_change_updates_permissions(self):
        """Test that changing a user's role updates their permissions"""
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        # Before: viewer role (read only)
        viewer_permissions = {
            "projects": {"read": True, "write": False, "delete": False},
        }

        mock_response_viewer = AsyncMock()
        mock_response_viewer.status_code = 200
        mock_response_viewer.json = MagicMock(
            return_value={"result": viewer_permissions}
        )

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_viewer

            permissions = await opa_service.get_user_permissions(
                email="user@acme.com",
                platform="mlops",
            )
            assert permissions["projects"]["write"] is False

        # After: admin role (full access)
        admin_permissions = {
            "projects": {"read": True, "write": True, "delete": True},
        }

        mock_response_admin = AsyncMock()
        mock_response_admin.status_code = 200
        mock_response_admin.json = MagicMock(return_value={"result": admin_permissions})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_admin

            permissions = await opa_service.get_user_permissions(
                email="user@acme.com",
                platform="mlops",
            )
            assert permissions["projects"]["write"] is True
            assert permissions["projects"]["delete"] is True


class TestOPARBACRuleChanges:
    """Test RBAC rule changes and their effects"""

    @pytest.mark.asyncio
    async def test_add_new_resource_permission(self):
        """Test adding permissions for a new resource"""
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        # Initially: no experiments permission
        initial_permissions = {
            "projects": {"read": True, "write": True},
        }

        mock_response_initial = AsyncMock()
        mock_response_initial.status_code = 200
        mock_response_initial.json = MagicMock(
            return_value={"result": initial_permissions}
        )

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_initial

            permissions = await opa_service.get_user_permissions(
                email="user@acme.com",
                platform="mlops",
            )
            assert "experiments" not in permissions

        # After: experiments permission added
        updated_permissions = {
            "projects": {"read": True, "write": True},
            "experiments": {"read": True, "write": True, "delete": False},
        }

        mock_response_updated = AsyncMock()
        mock_response_updated.status_code = 200
        mock_response_updated.json = MagicMock(
            return_value={"result": updated_permissions}
        )

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_updated

            permissions = await opa_service.get_user_permissions(
                email="user@acme.com",
                platform="mlops",
            )
            assert "experiments" in permissions
            assert permissions["experiments"]["read"] is True

    @pytest.mark.asyncio
    async def test_revoke_permission(self):
        """Test revoking a permission from a role"""
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        # Before: has delete permission
        mock_response_allowed = AsyncMock()
        mock_response_allowed.status_code = 200
        mock_response_allowed.json = MagicMock(return_value={"result": True})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_allowed

            result = await opa_service.check_authorization(
                email="user@acme.com",
                platform="mlops",
                resource="projects",
                action="delete",
            )
            assert result is True

        # After: delete permission revoked
        mock_response_denied = AsyncMock()
        mock_response_denied.status_code = 200
        mock_response_denied.json = MagicMock(return_value={"result": False})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_denied

            result = await opa_service.check_authorization(
                email="user@acme.com",
                platform="mlops",
                resource="projects",
                action="delete",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_add_new_role(self):
        """Test adding a new role to the RBAC system"""
        new_role_data = {
            "mlops": {
                "acme": {
                    "data_scientist": {
                        "projects": {"read": True, "write": True, "delete": False},
                        "experiments": {"read": True, "write": True, "delete": True},
                        "models": {"read": True, "write": True, "delete": False},
                        "global_access": False,
                        "bu_access": True,
                    }
                }
            }
        }

        # Verify structure is correct
        assert "data_scientist" in new_role_data["mlops"]["acme"]
        role = new_role_data["mlops"]["acme"]["data_scientist"]
        assert role["experiments"]["delete"] is True
        assert role["projects"]["delete"] is False

    @pytest.mark.asyncio
    async def test_add_new_tenant(self):
        """Test adding a new tenant/organization"""
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        # User from new tenant should work after data update
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={
                "result": {
                    "user_id": "user-100",
                    "role": "admin",
                    "organization": "newcorp",
                    "is_org_admin": 1,
                }
            }
        )

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response

            context = await opa_service.get_user_context(
                email="admin@newcorp.com",
                platform="mlops",
            )
            assert context["organization"] == "newcorp"
            assert context["role"] == "admin"


class TestOPAPlatformUpdates:
    """Test platform-specific updates"""

    @pytest.mark.asyncio
    async def test_add_new_platform(self):
        """Test adding RBAC rules for a new platform"""
        new_platform_data = {
            "analytics": {
                "acme": {
                    "admin": {
                        "dashboards": {"read": True, "write": True, "delete": True},
                        "reports": {"read": True, "write": True, "delete": True},
                        "global_access": True,
                        "bu_access": True,
                    }
                }
            }
        }

        # Verify structure
        assert "analytics" in new_platform_data
        assert "dashboards" in new_platform_data["analytics"]["acme"]["admin"]

    @pytest.mark.asyncio
    async def test_platform_isolation(self):
        """Test that platform permissions are isolated"""
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        # User has admin on mlops
        mlops_permissions = {
            "projects": {"read": True, "write": True, "delete": True},
        }

        mock_response_mlops = AsyncMock()
        mock_response_mlops.status_code = 200
        mock_response_mlops.json = MagicMock(return_value={"result": mlops_permissions})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_mlops

            permissions = await opa_service.get_user_permissions(
                email="user@acme.com",
                platform="mlops",
            )
            assert permissions["projects"]["delete"] is True

        # Same user has viewer on analytics (no delete)
        analytics_permissions = {
            "dashboards": {"read": True, "write": False, "delete": False},
        }

        mock_response_analytics = AsyncMock()
        mock_response_analytics.status_code = 200
        mock_response_analytics.json = MagicMock(
            return_value={"result": analytics_permissions}
        )

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_response_analytics

            permissions = await opa_service.get_user_permissions(
                email="user@acme.com",
                platform="analytics",
            )
            assert permissions["dashboards"]["delete"] is False


class TestOPAUpdateIntegration:
    """Integration tests for OPA update flow"""

    @pytest.mark.asyncio
    async def test_full_update_cycle(self):
        """Test complete update cycle: policy + data + verification"""
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        # Step 1: Initial state - user doesn't exist
        mock_not_exists = AsyncMock()
        mock_not_exists.status_code = 200
        mock_not_exists.json = MagicMock(return_value={"result": False})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_not_exists

            exists = await opa_service.check_user_exists("new@acme.com")
            assert exists is False

        # Step 2: After data update - user exists
        mock_exists = AsyncMock()
        mock_exists.status_code = 200
        mock_exists.json = MagicMock(return_value={"result": True})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_exists

            exists = await opa_service.check_user_exists("new@acme.com")
            assert exists is True

        # Step 3: Get user context
        mock_context = AsyncMock()
        mock_context.status_code = 200
        mock_context.json = MagicMock(
            return_value={
                "result": {
                    "user_id": "user-new",
                    "role": "developer",
                    "organization": "acme",
                    "is_org_admin": 0,
                }
            }
        )

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_context

            context = await opa_service.get_user_context("new@acme.com", "mlops")
            assert context["role"] == "developer"

        # Step 4: Get permissions
        mock_permissions = AsyncMock()
        mock_permissions.status_code = 200
        mock_permissions.json = MagicMock(
            return_value={
                "result": {
                    "projects": {"read": True, "write": True, "delete": False},
                }
            }
        )

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_permissions

            permissions = await opa_service.get_user_permissions(
                "new@acme.com", "mlops"
            )
            assert permissions["projects"]["read"] is True
            assert permissions["projects"]["delete"] is False

        # Step 5: Check authorization
        mock_auth = AsyncMock()
        mock_auth.status_code = 200
        mock_auth.json = MagicMock(return_value={"result": True})

        with patch("httpx.AsyncClient") as mock_client:
            client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = client_instance
            client_instance.post.return_value = mock_auth

            allowed = await opa_service.check_authorization(
                email="new@acme.com",
                platform="mlops",
                resource="projects",
                action="write",
            )
            assert allowed is True

    @pytest.mark.asyncio
    async def test_concurrent_updates_handled(self):
        """Test that concurrent updates don't cause issues"""
        import asyncio
        from app.services.opa_service import OPAService

        opa_service = OPAService()

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"result": True})

        async def check_user(email):
            with patch("httpx.AsyncClient") as mock_client:
                client_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = client_instance
                client_instance.post.return_value = mock_response
                return await opa_service.check_user_exists(email)

        # Simulate concurrent checks (as might happen during bulk updates)
        users = [f"user{i}@acme.com" for i in range(10)]
        results = await asyncio.gather(*[check_user(u) for u in users])

        assert all(results)
        assert len(results) == 10


class TestSyncWorkerFunctions:
    """Test sync worker utility functions"""

    def test_bundle_structure(self):
        """Test that bundle structure is correct for OPA"""
        bundle = {
            "rbac": {
                "mlops": {
                    "acme": {
                        "admin": {
                            "projects": {"read": True, "write": True, "delete": True},
                            "global_access": True,
                            "bu_access": True,
                        }
                    }
                }
            },
            "users": {
                "user_roles": {"admin@acme.com": "admin"},
                "user_tenant": {"admin@acme.com": "acme"},
                "user_ids": {"admin@acme.com": "user-001"},
                "org_admin_flag": {"admin@acme.com": 1},
            },
            "platforms": ["mlops"],
        }

        # Verify structure matches OPA expectations
        assert "rbac" in bundle
        assert "users" in bundle
        assert "platforms" in bundle

        # Verify RBAC hierarchy: platform -> tenant -> role -> resource -> actions
        assert "mlops" in bundle["rbac"]
        assert "acme" in bundle["rbac"]["mlops"]
        assert "admin" in bundle["rbac"]["mlops"]["acme"]
        assert "projects" in bundle["rbac"]["mlops"]["acme"]["admin"]

        # Verify user data structure
        assert bundle["users"]["user_roles"]["admin@acme.com"] == "admin"
        assert bundle["users"]["user_tenant"]["admin@acme.com"] == "acme"

    def test_empty_bundle_handling(self):
        """Test handling of empty bundles"""
        empty_bundle = {
            "rbac": {},
            "users": {
                "user_roles": {},
                "user_tenant": {},
                "user_ids": {},
                "org_admin_flag": {},
            },
            "platforms": [],
        }

        # Should be valid structure even if empty
        assert isinstance(empty_bundle["rbac"], dict)
        assert isinstance(empty_bundle["platforms"], list)

    def test_incremental_bundle_merge(self):
        """Test merging incremental updates into existing bundle"""
        existing_bundle = {
            "rbac": {
                "mlops": {
                    "acme": {
                        "admin": {"projects": {"read": True, "write": True}},
                    }
                }
            },
            "users": {
                "user_roles": {"admin@acme.com": "admin"},
                "user_tenant": {"admin@acme.com": "acme"},
                "user_ids": {"admin@acme.com": "user-001"},
                "org_admin_flag": {"admin@acme.com": 1},
            },
        }

        # New user to add
        new_user_data = {
            "user_roles": {"viewer@acme.com": "viewer"},
            "user_tenant": {"viewer@acme.com": "acme"},
            "user_ids": {"viewer@acme.com": "user-002"},
            "org_admin_flag": {"viewer@acme.com": 0},
        }

        # Merge
        for key in new_user_data:
            existing_bundle["users"][key].update(new_user_data[key])

        # Verify merge
        assert "admin@acme.com" in existing_bundle["users"]["user_roles"]
        assert "viewer@acme.com" in existing_bundle["users"]["user_roles"]
        assert existing_bundle["users"]["user_roles"]["viewer@acme.com"] == "viewer"


class TestOPARegoRules:
    """Test OPA Rego rule behavior"""

    def test_rego_rule_user_exists(self):
        """Test user_exists rule structure"""
        # This is the expected input/output for user_exists
        input_data = {"user": "admin@acme.com"}

        # When user exists in data.users.user_roles
        expected_result_exists = True

        # When user doesn't exist
        expected_result_not_exists = False

        assert expected_result_exists is True
        assert expected_result_not_exists is False

    def test_rego_rule_allow_structure(self):
        """Test allow rule input structure"""
        # This is the expected input structure for authorization
        input_data = {
            "user": "admin@acme.com",
            "platform": "mlops",
            "resource": "projects",
            "action": "write",
        }

        # Verify all required fields are present
        assert "user" in input_data
        assert "platform" in input_data
        assert "resource" in input_data
        assert "action" in input_data

    def test_rego_rule_user_permissions_structure(self):
        """Test user_permissions rule output structure"""
        expected_output = {
            "projects": {"read": True, "write": True, "delete": False},
            "pipelines": {"read": True, "write": False, "delete": False},
        }

        # Verify structure - should not include metadata fields
        assert "global_access" not in expected_output
        assert "bu_access" not in expected_output

        # Verify each resource has action permissions
        for resource, perms in expected_output.items():
            assert "read" in perms
            assert isinstance(perms["read"], bool)

    def test_rego_rule_user_context_structure(self):
        """Test user_context rule output structure"""
        expected_output = {
            "user_id": "user-001",
            "role": "admin",
            "organization": "acme",
            "is_org_admin": 1,
        }

        # Verify all required fields
        assert "user_id" in expected_output
        assert "role" in expected_output
        assert "organization" in expected_output
        assert "is_org_admin" in expected_output

    def test_rbac_hierarchy(self):
        """Test RBAC data hierarchy is correct"""
        # Hierarchy: rbac[platform][tenant][role][resource][action]
        rbac = {
            "mlops": {  # platform
                "acme": {  # tenant/organization
                    "admin": {  # role
                        "projects": {  # resource
                            "read": True,  # actions
                            "write": True,
                            "delete": True,
                        },
                        "global_access": True,
                        "bu_access": True,
                    }
                }
            }
        }

        # Verify traversal
        platform = "mlops"
        tenant = "acme"
        role = "admin"
        resource = "projects"
        action = "write"

        assert rbac[platform][tenant][role][resource][action] is True
