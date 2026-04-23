# Testing Guide

Comprehensive guide for testing the User Management System.

## Test Structure

```
v2/auth-server/tests/
├── conftest.py              # Shared fixtures and configuration
├── test_auth.py             # Authentication endpoint tests
├── test_authorize.py        # Authorization endpoint tests
├── test_manage.py           # Management API endpoint tests
├── test_token_service.py    # Token service unit tests
├── test_token_lifecycle.py  # Token lifecycle (create, refresh, revoke) tests
├── test_opa_service.py      # OPA service unit tests
├── test_opa_updates.py      # OPA data sync/update tests
└── test_integration.py      # End-to-end integration tests
```

## Running Tests

### Prerequisites

```bash
cd v2/auth-server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### Run All Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run specific test class
pytest tests/test_auth.py::TestLoginEndpoint

# Run specific test
pytest tests/test_auth.py::TestLoginEndpoint::test_login_success
```

### Run Tests with Docker

```bash
# Build test image
docker build -t auth-server-test -f Dockerfile .

# Run tests in container
docker run --rm auth-server-test pytest -v
```

## Test Results (142 passed, 0 failed)

Last run: 2026-04-23 | Python 3.12.3 | pytest 7.4.4 | 4.96s

### test_auth.py — Authentication Endpoints (12 tests)

Tests for the SSO login, callback, refresh, and logout API endpoints. External services (Redis, OPA, IdP) are mocked.

| # | Test | Result | What it verifies |
|---|------|--------|------------------|
| 1 | `TestLoginEndpoint::test_login_success` | PASSED | `POST /auth/login` with valid platform and org returns 200 with a `login_url` containing the IdP authorize URL. |
| 2 | `TestLoginEndpoint::test_login_invalid_platform` | PASSED | `POST /auth/login` with an unrecognized platform returns 400 with "Invalid platform" error. |
| 3 | `TestLoginEndpoint::test_login_missing_platform` | PASSED | `POST /auth/login` without `platform` field returns 422 (Pydantic validation error). |
| 4 | `TestLoginEndpoint::test_login_missing_org_name` | PASSED | `POST /auth/login` without `org_name` field returns 422 (Pydantic validation error). |
| 5 | `TestLoginEndpoint::test_login_session_store_failure` | PASSED | When Redis fails to store login state, `POST /auth/login` returns 500 with "Failed to initialize" error. |
| 6 | `TestCallbackEndpoint::test_callback_invalid_state` | PASSED | `GET /auth/callback` with an unknown `state` parameter returns 400 "Invalid or expired state". |
| 7 | `TestCallbackEndpoint::test_callback_missing_code` | PASSED | `GET /auth/callback` without the `code` query parameter returns 422 (validation error). |
| 8 | `TestCallbackEndpoint::test_callback_user_not_registered` | PASSED | After a valid IdP exchange, if the user email is not in OPA, callback returns 403 "not registered". |
| 9 | `TestRefreshEndpoint::test_refresh_invalid_token` | PASSED | `POST /auth/refresh` with a garbage string returns 401. |
| 10 | `TestRefreshEndpoint::test_refresh_missing_token` | PASSED | `POST /auth/refresh` with empty body returns 422 (missing `refresh_token` field). |
| 11 | `TestLogoutEndpoint::test_logout_success` | PASSED | `POST /auth/logout` with no token returns 200 `{success: true}`. |
| 12 | `TestLogoutEndpoint::test_logout_with_invalid_token` | PASSED | `POST /auth/logout` with a bad token still returns 200 (graceful handling — revocation may silently fail). |

### test_authorize.py — Authorization Endpoints (11 tests)

Tests for the `/authorize`, `/authorize/me`, and `/authorize/batch` endpoints. OPA is mocked; JWT validation is real.

| # | Test | Result | What it verifies |
|---|------|--------|------------------|
| 13 | `TestAuthorizeEndpoint::test_authorize_success` | PASSED | `POST /authorize` with valid JWT and a resource/action returns 200 with `allowed: true`, plus `user_id`, `organization`, `role`. |
| 14 | `TestAuthorizeEndpoint::test_authorize_denied` | PASSED | When OPA returns `allowed: false`, the response correctly reflects the denial (status is still 200, body has `allowed: false`). |
| 15 | `TestAuthorizeEndpoint::test_authorize_no_token` | PASSED | `POST /authorize` without an `Authorization` header returns 403 (no credentials). |
| 16 | `TestAuthorizeEndpoint::test_authorize_invalid_token` | PASSED | `POST /authorize` with `Bearer invalid-token` returns 401. |
| 17 | `TestAuthorizeEndpoint::test_authorize_expired_token` | PASSED | `POST /authorize` with an expired JWT returns 401 with "expired" in the error message. |
| 18 | `TestAuthorizeEndpoint::test_authorize_missing_resource` | PASSED | `POST /authorize` with a body missing the `resource` field returns 422 (validation error). |
| 19 | `TestAuthorizeEndpoint::test_authorize_with_context` | PASSED | `POST /authorize` with an optional `context` object (e.g. `project_id`, `bu_id`) returns 200 — the extra context is accepted. |
| 20 | `TestMeEndpoint::test_me_success` | PASSED | `GET /authorize/me` with a valid JWT returns 200 with `email`, `user_id`, `organization`, `platform`, `permissions` decoded from the token. |
| 21 | `TestMeEndpoint::test_me_no_token` | PASSED | `GET /authorize/me` without a token returns 403. |
| 22 | `TestBatchAuthorizeEndpoint::test_batch_authorize_success` | PASSED | `POST /authorize/batch` with 3 resource/action pairs returns 200 with 3 results, each containing an `allowed` field. |
| 23 | `TestBatchAuthorizeEndpoint::test_batch_authorize_empty` | PASSED | `POST /authorize/batch` with an empty list returns 200 with an empty `results` array. |

### test_manage.py — Management API Endpoints (47 tests)

Tests for all 17 management endpoints (orgs, roles, permissions, users, audit). The database layer (`manage_service`) is mocked — these tests verify routing, JWT authentication, org-admin authorization, request validation, error mapping (409 on duplicates, 404 on missing resources), and response shaping.

| # | Test | Result | What it verifies |
|---|------|--------|------------------|
| 24 | `TestListOrgs::test_list_orgs_success` | PASSED | `GET /manage/orgs` with admin JWT returns 200 with org list and `total` count. |
| 25 | `TestListOrgs::test_list_orgs_non_admin_rejected` | PASSED | `GET /manage/orgs` with a JWT where `org_admin=0` returns 403 "org admin privileges". |
| 26 | `TestListOrgs::test_list_orgs_no_token` | PASSED | `GET /manage/orgs` with no Authorization header returns 403. |
| 27 | `TestCreateOrg::test_create_org_success` | PASSED | `POST /manage/orgs` with `{name}` returns 201 with the created org's `id` and `name`. |
| 28 | `TestCreateOrg::test_create_org_duplicate` | PASSED | When the DB raises a unique constraint violation, the endpoint returns 409 "already exists". |
| 29 | `TestCreateOrg::test_create_org_missing_name` | PASSED | `POST /manage/orgs` with empty body returns 422 (Pydantic validation — `name` is required). |
| 30 | `TestGetOrg::test_get_org_success` | PASSED | `GET /manage/orgs/{id}` returns 200 with the org details. |
| 31 | `TestGetOrg::test_get_org_not_found` | PASSED | `GET /manage/orgs/{unknown_id}` returns 404. |
| 32 | `TestUpdateOrg::test_update_org_success` | PASSED | `PUT /manage/orgs/{id}` with `{name}` returns 200 with the updated name. |
| 33 | `TestUpdateOrg::test_update_org_not_found` | PASSED | `PUT /manage/orgs/{unknown_id}` returns 404. |
| 34 | `TestUpdateOrg::test_update_org_duplicate_name` | PASSED | When renaming to an existing org name, returns 409. |
| 35 | `TestDeleteOrg::test_delete_org_success` | PASSED | `DELETE /manage/orgs/{id}` returns 204 when the org has no roles. |
| 36 | `TestDeleteOrg::test_delete_org_has_roles` | PASSED | `DELETE /manage/orgs/{id}` returns 409 "still has roles" when the org has dependent roles. |
| 37 | `TestListRoles::test_list_roles_success` | PASSED | `GET /manage/orgs/{id}/roles` returns 200 with role list including `global_access`, `bu_access`, `org_name`. |
| 38 | `TestCreateRole::test_create_role_success` | PASSED | `POST .../roles` with `{name, global_access, bu_access}` returns 201 with full role response. |
| 39 | `TestCreateRole::test_create_role_duplicate` | PASSED | Duplicate role name in same org returns 409. |
| 40 | `TestCreateRole::test_create_role_org_not_found` | PASSED | Creating a role in a non-existent org returns 404. |
| 41 | `TestGetRole::test_get_role_success` | PASSED | `GET .../roles/{id}` returns 200 with role detail including nested `permissions[]` array. |
| 42 | `TestGetRole::test_get_role_not_found` | PASSED | `GET .../roles/{unknown_id}` returns 404. |
| 43 | `TestUpdateRole::test_update_role_success` | PASSED | `PUT .../roles/{id}` with partial update returns 200 with updated fields. |
| 44 | `TestUpdateRole::test_update_role_empty_body` | PASSED | `PUT .../roles/{id}` with `{}` returns 400 "No fields to update". |
| 45 | `TestUpdateRole::test_update_role_not_found` | PASSED | `PUT .../roles/{unknown_id}` returns 404. |
| 46 | `TestDeleteRole::test_delete_role_success` | PASSED | `DELETE .../roles/{id}` returns 204 when the role has no users. |
| 47 | `TestDeleteRole::test_delete_role_has_users` | PASSED | `DELETE .../roles/{id}` returns 409 "still has users" when users are assigned to the role. |
| 48 | `TestGetPermissions::test_get_permissions_success` | PASSED | `GET .../permissions` returns 200 with `role_name`, `org_name`, `permissions[]`, and `total`. |
| 49 | `TestGetPermissions::test_get_permissions_role_not_found` | PASSED | `GET .../permissions` for unknown role returns 404. |
| 50 | `TestSetPermissions::test_set_permissions_success` | PASSED | `PUT .../permissions` with a list of permission objects returns 200 with the full updated permission set. |
| 51 | `TestSetPermissions::test_set_permissions_role_not_found` | PASSED | `PUT .../permissions` for unknown role returns 404. |
| 52 | `TestSetPermissions::test_set_permissions_empty_list` | PASSED | `PUT .../permissions` with `{permissions: []}` returns 422 (Pydantic `min_length=1` validation). |
| 53 | `TestDeletePermission::test_delete_permission_success` | PASSED | `DELETE .../permissions/pipelines` returns 204. |
| 54 | `TestDeletePermission::test_delete_permission_not_found` | PASSED | `DELETE .../permissions/nonexistent` returns 404. |
| 55 | `TestListUsers::test_list_users_success` | PASSED | `GET .../users` returns 200 with user list including `email`, `user_uid`, `role_name`, `org_name`, `is_org_admin`. |
| 56 | `TestAddUser::test_add_user_success` | PASSED | `POST .../users` with `{email, role_name, user_uid, is_org_admin}` returns 201 with full user response. |
| 57 | `TestAddUser::test_add_user_duplicate_email` | PASSED | Duplicate email returns 409. |
| 58 | `TestAddUser::test_add_user_role_not_found` | PASSED | Referencing a non-existent role name returns 404. |
| 59 | `TestAddUser::test_add_user_invalid_email` | PASSED | An invalid email format (e.g. `"not-an-email"`) returns 422 (Pydantic `EmailStr` validation). |
| 60 | `TestGetUser::test_get_user_success` | PASSED | `GET .../users/{id}` returns 200 with user details. |
| 61 | `TestGetUser::test_get_user_not_found` | PASSED | `GET .../users/{unknown_id}` returns 404. |
| 62 | `TestUpdateUser::test_update_user_role` | PASSED | `PUT .../users/{id}` with `{role_name, is_org_admin}` returns 200 with updated values. |
| 63 | `TestUpdateUser::test_update_user_empty_body` | PASSED | `PUT .../users/{id}` with `{}` returns 400 "No fields to update". |
| 64 | `TestUpdateUser::test_update_user_not_found` | PASSED | `PUT .../users/{unknown_id}` returns 404. |
| 65 | `TestUpdateUser::test_update_user_role_not_found` | PASSED | Referencing a non-existent role name in update returns 404. |
| 66 | `TestRemoveUser::test_remove_user_success` | PASSED | `DELETE .../users/{id}` returns 204. |
| 67 | `TestRemoveUser::test_remove_user_not_found` | PASSED | `DELETE .../users/{unknown_id}` returns 404. |
| 68 | `TestAuditLog::test_audit_log_success` | PASSED | `GET /manage/audit?org_name=acme&limit=10` returns 200 with audit entries including `action`, `actor_email`, `details`. |
| 69 | `TestAuditLog::test_audit_log_no_filter` | PASSED | `GET /manage/audit` without filters returns 200 with `{entries: [], total: 0}` when no entries exist. |
| 70 | `TestAuditLog::test_audit_log_non_admin_rejected` | PASSED | `GET /manage/audit` with a non-admin JWT returns 403. |

### test_integration.py — Integration Flows (6 tests)

Tests complete multi-step flows (login-to-callback, refresh-with-updated-permissions, authorize-after-me). External services are mocked but the FastAPI app runs end-to-end through its middleware and routing.

| # | Test | Result | What it verifies |
|---|------|--------|------------------|
| 71 | `TestHealthEndpoints::test_root_endpoint` | PASSED | `GET /` returns 200 with `status: "running"` and a `version` field. |
| 72 | `TestHealthEndpoints::test_health_endpoint` | PASSED | `GET /health` returns 200 with `status: "healthy"`. |
| 73 | `TestFullLoginFlow::test_login_to_callback_flow` | PASSED | Full login-to-callback: initiates login (gets `login_url`), then simulates callback with mocked IdP exchange and ID token verification. Verifies the final response contains `success: true`, `access_token`, `refresh_token`, and correct `email`. |
| 74 | `TestTokenRefreshFlow::test_refresh_updates_permissions` | PASSED | Creates a refresh token, mocks OPA to return *new* permissions (with `projects.delete: true`), calls `POST /auth/refresh`, then decodes the new access token and confirms it contains the updated permissions from OPA. |
| 75 | `TestAuthorizationFlow::test_authorize_with_valid_token` | PASSED | Uses a valid JWT to call `POST /authorize` and confirms `allowed: true`. |
| 76 | `TestAuthorizationFlow::test_me_then_authorize` | PASSED | Calls `GET /authorize/me` first (verifies user info), then calls `POST /authorize` (verifies authorization decision) — tests the two endpoints in sequence. |

### test_opa_service.py — OPA Service Unit Tests (10 tests)

Tests the `OPAService` class in isolation by mocking the HTTP calls to OPA. Verifies correct request formatting and response parsing.

| # | Test | Result | What it verifies |
|---|------|--------|------------------|
| 77 | `test_check_user_exists_true` | PASSED | When OPA returns `{result: true}`, `check_user_exists()` returns `True`. |
| 78 | `test_check_user_exists_false` | PASSED | When OPA returns `{result: false}`, `check_user_exists()` returns `False`. |
| 79 | `test_check_user_exists_opa_error` | PASSED | When OPA returns HTTP 500, `check_user_exists()` gracefully returns `False` instead of raising. |
| 80 | `test_get_user_context` | PASSED | `get_user_context()` returns the full context dict (`user_id`, `role`, `organization`, `is_org_admin`) from OPA. |
| 81 | `test_get_user_permissions` | PASSED | `get_user_permissions()` returns the permission dict (e.g. `{projects: {read: true, ...}}`) from OPA. |
| 82 | `test_get_user_permissions_empty` | PASSED | When OPA returns `{result: null}` (no permissions), `get_user_permissions()` returns `{}` (empty dict, not `None`). |
| 83 | `test_check_authorization_allowed` | PASSED | When OPA returns `{result: true}` for an allow query, `check_authorization()` returns `True`. |
| 84 | `test_check_authorization_denied` | PASSED | When OPA returns `{result: false}`, `check_authorization()` returns `False`. |
| 85 | `test_get_authorization_response` | PASSED | `get_authorization_response()` returns the full response dict (`allowed`, `user_id`, `organization`, `role`, `is_org_admin`). |
| 86 | `test_connection_error` | PASSED | When the HTTP connection to OPA fails entirely (`RequestError`), `check_user_exists()` returns `False` instead of crashing. |

### test_opa_updates.py — OPA Data and Policy Update Tests (20 tests)

Tests the OPA policy/data update mechanisms, RBAC rule changes, platform isolation, sync worker bundle structure, and Rego rule contracts.

| # | Test | Result | What it verifies |
|---|------|--------|------------------|
| 87 | `TestOPAPolicyUpdates::test_push_policy_success` | PASSED | A valid Rego policy pushed via `PUT /v1/policies/authz` gets a 200 response from OPA. |
| 88 | `TestOPAPolicyUpdates::test_push_invalid_policy_rejected` | PASSED | Invalid Rego syntax is rejected by OPA with 400 and `invalid_parameter` error code. |
| 89 | `TestOPAPolicyUpdates::test_policy_update_changes_authorization` | PASSED | After a policy update, a previously denied action becomes allowed — the OPAService correctly reflects the new policy. |
| 90 | `TestOPADataUpdates::test_push_rbac_data_success` | PASSED | A well-formed RBAC bundle (`platform -> tenant -> role -> resource -> actions`) is accepted by OPA (204). |
| 91 | `TestOPADataUpdates::test_push_user_data_success` | PASSED | A user data bundle (`user_roles`, `user_tenant`, `user_ids`, `org_admin_flag`) is accepted by OPA (204). |
| 92 | `TestOPADataUpdates::test_add_new_user_updates_authorization` | PASSED | A user that didn't exist (`check_user_exists` = false) becomes findable after a data update (`check_user_exists` = true). |
| 93 | `TestOPADataUpdates::test_role_change_updates_permissions` | PASSED | After changing a user's role from viewer to admin, `get_user_permissions()` returns the expanded permission set (write and delete become true). |
| 94 | `TestOPARBACRuleChanges::test_add_new_resource_permission` | PASSED | Adding a new resource (e.g. `experiments`) to a role's permissions makes it appear in subsequent `get_user_permissions()` calls. |
| 95 | `TestOPARBACRuleChanges::test_revoke_permission` | PASSED | After revoking delete permission, `check_authorization(action="delete")` correctly returns `False`. |
| 96 | `TestOPARBACRuleChanges::test_add_new_role` | PASSED | A new role structure (`data_scientist` with specific resource permissions) is well-formed and passes structural validation. |
| 97 | `TestOPARBACRuleChanges::test_add_new_tenant` | PASSED | After adding a new tenant (`newcorp`), `get_user_context()` for a user in that tenant returns the correct `organization` and `role`. |
| 98 | `TestOPAPlatformUpdates::test_add_new_platform` | PASSED | A new platform (`analytics`) with its own resource structure (`dashboards`, `reports`) is well-formed for OPA. |
| 99 | `TestOPAPlatformUpdates::test_platform_isolation` | PASSED | The same user has `projects.delete: true` on mlops but `dashboards.delete: false` on analytics — platforms are isolated. |
| 100 | `TestOPAUpdateIntegration::test_full_update_cycle` | PASSED | Full cycle: user doesn't exist -> data update -> user exists -> get context (developer role) -> get permissions (read+write, no delete) -> check authorization (write allowed). |
| 101 | `TestOPAUpdateIntegration::test_concurrent_updates_handled` | PASSED | 10 concurrent `check_user_exists()` calls via `asyncio.gather` all complete successfully without errors. |
| 102 | `TestSyncWorkerFunctions::test_bundle_structure` | PASSED | Validates the full OPA bundle structure: `rbac` (platform->tenant->role->resource->actions), `users` (4 mapping dicts), `platforms` (list). |
| 103 | `TestSyncWorkerFunctions::test_empty_bundle_handling` | PASSED | An empty bundle (no data) is still structurally valid — empty dicts and lists pass validation. |
| 104 | `TestSyncWorkerFunctions::test_incremental_bundle_merge` | PASSED | Merging a new user into an existing bundle preserves the original user and correctly adds the new one. |
| 105 | `TestOPARegoRules::test_rego_rule_user_exists` | PASSED | Validates the expected input/output contract for the `user_exists` Rego rule. |
| 106 | `TestOPARegoRules::test_rego_rule_allow_structure` | PASSED | Validates the `allow` rule requires all 4 input fields: `user`, `platform`, `resource`, `action`. |
| 107 | `TestOPARegoRules::test_rego_rule_user_permissions_structure` | PASSED | Validates permissions output structure: resource-level dicts with `read`/`write`/`delete` booleans, no metadata fields mixed in. |
| 108 | `TestOPARegoRules::test_rego_rule_user_context_structure` | PASSED | Validates user context output has all required fields: `user_id`, `role`, `organization`, `is_org_admin`. |
| 109 | `TestOPARegoRules::test_rbac_hierarchy` | PASSED | Validates the RBAC data hierarchy traversal: `rbac[platform][tenant][role][resource][action]` resolves to a boolean. |

### test_token_lifecycle.py — JWT Token Lifecycle Tests (21 tests)

Comprehensive tests covering every phase of token life: creation, validation, expiration, revocation, refresh, and security properties.

| # | Test | Result | What it verifies |
|---|------|--------|------------------|
| 110 | `TestTokenCreationLifecycle::test_access_token_structure` | PASSED | Access token contains all 10 required claims: `email`, `userID`, `organization`, `platform`, `org_admin`, `permissions`, `licence`, `iat`, `exp`, `type`. Values match inputs. |
| 111 | `TestTokenCreationLifecycle::test_refresh_token_structure` | PASSED | Refresh token contains `email`, `platform`, `jti`, `iat`, `exp`, `type="refresh"` — and does NOT contain `permissions`, `licence`, or `userID` (minimal by design). |
| 112 | `TestTokenCreationLifecycle::test_token_pair_creation` | PASSED | Access and refresh tokens created for the same user share `email` and `platform`, but access expires sooner than refresh. Both decode as valid JWTs with correct `type`. |
| 113 | `TestTokenValidationLifecycle::test_valid_token_decodes` | PASSED | A freshly created token decodes successfully via `decode_token()`. |
| 114 | `TestTokenValidationLifecycle::test_tampered_token_rejected` | PASSED | A token with a modified payload section raises `JWTError` on decode (signature mismatch). |
| 115 | `TestTokenValidationLifecycle::test_wrong_secret_rejected` | PASSED | A token signed with a different secret key raises `JWTError` on decode. |
| 116 | `TestTokenValidationLifecycle::test_malformed_token_rejected` | PASSED | Non-JWT strings (`"not-a-valid-jwt"`, `"a.b"`, `""`) all raise `JWTError`. |
| 117 | `TestTokenValidationLifecycle::test_refresh_token_validation` | PASSED | `validate_refresh_token()` accepts a properly formed refresh token and returns decoded claims with `type: "refresh"`. |
| 118 | `TestTokenValidationLifecycle::test_access_token_fails_refresh_validation` | PASSED | Passing an access token to `validate_refresh_token()` raises `ValueError("not a refresh token")`. |
| 119 | `TestTokenExpirationLifecycle::test_expired_token_rejected` | PASSED | A token with `exp` in the past raises `ExpiredSignatureError` on decode. |
| 120 | `TestTokenExpirationLifecycle::test_access_token_expiry_time` | PASSED | Access token `expires` datetime is within 1 minute of `now + ACCESS_TOKEN_EXPIRE_MINUTES`. |
| 121 | `TestTokenExpirationLifecycle::test_refresh_token_expiry_time` | PASSED | Refresh token `expires` datetime is within ~2.4 hours of `now + REFRESH_TOKEN_EXPIRE_DAYS`. |
| 122 | `TestTokenExpirationLifecycle::test_token_near_expiry` | PASSED | A token expiring in 5 seconds is still valid right now — near-expiry tokens are not prematurely rejected. |
| 123 | `TestTokenRevocationLifecycle::test_revoke_refresh_token` | PASSED | `revoke_refresh_token()` calls `session_service.revoke_token()` with the token's `jti` and returns `True`. |
| 124 | `TestTokenRevocationLifecycle::test_revoked_token_invalid` | PASSED | After revocation (mock `is_token_revoked` returns `True`), `is_refresh_token_valid()` returns `False`. |
| 125 | `TestTokenRevocationLifecycle::test_valid_unrevoked_token` | PASSED | A non-revoked token that exists in Redis is reported as valid by `is_refresh_token_valid()`. |
| 126 | `TestTokenRefreshLifecycle::test_refresh_flow_new_permissions` | PASSED | Creating a new access token with updated permissions (simulating a refresh) produces a JWT with the new permissions, not the old ones. |
| 127 | `TestTokenRefreshLifecycle::test_refresh_token_reuse` | PASSED | The same refresh token can be validated 3 times — the `jti` stays the same each time (no rotation). |
| 128 | `TestTokenSecurityLifecycle::test_token_contains_no_sensitive_data` | PASSED | Access token claims do not contain `password`, `secret`, or `api_key` fields. |
| 129 | `TestTokenSecurityLifecycle::test_tokens_are_unique` | PASSED | 5 tokens created for different users are all distinct strings, and each decodes to the correct email. |
| 130 | `TestTokenSecurityLifecycle::test_refresh_tokens_have_unique_jti` | PASSED | 10 refresh tokens for the same user all have unique `jti` values (UUID collision check). |
| 131 | `TestTokenSecurityLifecycle::test_algorithm_consistency` | PASSED | The JWT header's `alg` field matches `settings.ALGORITHM` (`HS256`). |
| 132 | `TestLicenceInToken::test_default_licence_included` | PASSED | When no licence is provided, the hardcoded default licence is embedded in the access token with the user's organization. |
| 133 | `TestLicenceInToken::test_custom_licence_included` | PASSED | When a custom licence dict is passed, it overrides the default — the token contains the custom licence exactly. |

### test_token_service.py — Token Service Unit Tests (9 tests)

Focused unit tests for `TokenService` methods and edge cases.

| # | Test | Result | What it verifies |
|---|------|--------|------------------|
| 134 | `TestTokenService::test_create_access_token` | PASSED | `create_access_token()` returns a valid JWT with all expected claims (`email`, `userID`, `organization`, `platform`, `org_admin`, `type`, `permissions`, `licence`, `exp`, `iat`). |
| 135 | `TestTokenService::test_access_token_expiry` | PASSED | The expiry datetime returned by `create_access_token()` is within 1 minute of `now + ACCESS_TOKEN_EXPIRE_MINUTES`. |
| 136 | `TestTokenService::test_create_refresh_token` | PASSED | `create_refresh_token()` returns a JWT with `email`, `platform`, `type="refresh"`, `jti`, and `exp`. Redis `store_refresh_token` is called. |
| 137 | `TestTokenService::test_decode_token` | PASSED | `decode_token()` round-trips a created token and returns matching claims. |
| 138 | `TestTokenService::test_validate_refresh_token` | PASSED | `validate_refresh_token()` accepts a properly formed refresh token. |
| 139 | `TestTokenService::test_validate_refresh_token_wrong_type` | PASSED | `validate_refresh_token()` raises `ValueError("not a refresh token")` when given an access token. |
| 140 | `TestTokenServiceEdgeCases::test_create_token_with_special_characters_in_email` | PASSED | Emails with `+` characters (e.g. `user+test@example.com`) are preserved correctly in the JWT. |
| 141 | `TestTokenServiceEdgeCases::test_create_token_with_empty_permissions` | PASSED | An empty permissions dict `{}` is correctly embedded and decoded. |
| 142 | `TestTokenServiceEdgeCases::test_create_token_with_complex_permissions` | PASSED | A complex permissions structure (multiple resources + metadata flags) round-trips through JWT encoding/decoding without data loss. |

---

## Test Categories

### 1. Unit Tests

Test individual components in isolation.

```bash
# Run unit tests only
pytest tests/test_token_service.py tests/test_opa_service.py -v
```

### 2. API Tests

Test API endpoints with mocked dependencies.

```bash
# Run API tests
pytest tests/test_auth.py tests/test_authorize.py -v
```

### 3. Integration Tests

Test complete flows with mocked external services.

```bash
# Run integration tests
pytest tests/test_integration.py -v
```

### 4. End-to-End Tests (E2E)

Test with real running services.

```bash
# Start services
cd v2
docker-compose up -d

# Wait for services to be ready
sleep 30

# Run E2E tests
pytest tests/test_e2e.py -v --e2e

# Stop services
docker-compose down
```

### 5. Interactive Browser E2E Test

A comprehensive E2E test that uses a real browser for SSO login with Keycloak.

```bash
cd v2

# Ensure services are running
docker-compose up -d

# Activate virtual environment
source venv/bin/activate

# Install Playwright if needed
pip install playwright
playwright install chromium

# Run the interactive test
python e2e_interactive_test.py
```

**What this test does:**

1. **Health Check** - Verifies all services are running (Auth Server, OPA, Keycloak, PostgreSQL)
2. **Browser Login** - Opens a real browser to Keycloak login page
3. **Manual Authentication** - You log in manually (native or federated IdP)
4. **Token Capture** - Captures JWT tokens from callback
5. **Token Analysis** - Decodes and displays token claims
6. **Authorization Test** - Tests permission checks with current role
7. **Role Change** - Modifies user role in PostgreSQL (viewer ↔ admin)
8. **CDC Sync** - Waits for Debezium to sync changes to OPA (~2-5s)
9. **Token Refresh** - Gets new token with updated permissions
10. **Permission Verification** - Confirms permissions changed correctly
11. **Cleanup** - Resets user role

**Test Users for Interactive Test:**

| Login Type | Credentials |
|------------|-------------|
| Native (Keycloak) | `testuser@acme.com` / `testpassword123` |
| Native (Keycloak) | `admin@acme.com` / `adminpassword123` |
| Federated (Okta) | Click "Login with Okta" button |

**Sample Output:**

```
======================================================================
            Interactive E2E Test: Authorization Server v2             
======================================================================

[STEP 0] Service Health Check
  ▶ TEST: Auth Server
    ✓ PASS: Auth Server is healthy
  ▶ TEST: OPA
    ✓ PASS: OPA is healthy
  ▶ TEST: Keycloak
    ✓ PASS: Keycloak is healthy
  ▶ TEST: PostgreSQL
    ✓ PASS: PostgreSQL is healthy

[STEP 1] Interactive Browser SSO Login
  ▶ TEST: Initiate login via Auth Server
    ✓ PASS: Got authorization URL
  ▶ TEST: Browser Login (Manual)
    ⏳ WAITING: Complete the login in the browser...
    ✓ PASS: Login completed!
    ✓ LOGIN SUCCESSFUL!
      • Email: testuser@acme.com
      • Organization: acme

[STEP 5] Modify User Role in Database
  ▶ TEST: Change role: viewer → admin
    ✓ PASS: Role updated to admin

[STEP 6] Wait for CDC Pipeline Sync
  ▶ TEST: Wait for CDC sync to OPA
    → Expecting role to become 'admin'
    ✓ PASS: OPA synced after 2s - role is now 'admin'

[STEP 7] Refresh JWT Token
    📊 PERMISSION COMPARISON:
      Before (viewer):
        projects: {'delete': False, 'read': True, 'write': False}
      After (admin):
        projects: {'delete': True, 'read': True, 'write': True}
    ✓ PASS: Permissions changed correctly!

======================================================================
                   E2E TEST COMPLETED SUCCESSFULLY!                   
======================================================================
```

### 6. Non-Interactive E2E Test

For CI/CD pipelines, use the test-login endpoint (bypasses SSO):

```bash
cd v2
source venv/bin/activate
python e2e_test.py
```

This test uses the `/api/v1/auth/test-login` endpoint which is only available when `DEBUG=true`.

## Test Fixtures

### Available Fixtures

| Fixture | Description |
|---------|-------------|
| `client` | Synchronous FastAPI test client |
| `async_client` | Asynchronous test client |
| `mock_user_context` | Mock user context from OPA |
| `mock_permissions` | Mock permissions from OPA |
| `valid_access_token` | Valid JWT access token (with `org_admin=1`) |
| `non_admin_access_token` | Valid JWT without org admin privileges (`org_admin=0`) |
| `expired_access_token` | Expired JWT for testing |
| `mock_opa_service` | Mocked OPA service |
| `mock_session_service` | Mocked Redis session service |

### Using Fixtures

```python
def test_authorize_with_valid_token(
    self, 
    client: TestClient, 
    valid_access_token, 
    mock_opa_service
):
    """Test authorization with valid token"""
    with patch("app.routers.authorize.opa_service", mock_opa_service):
        response = client.post(
            "/api/v1/authorize",
            json={"resource": "projects", "action": "write"},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )

    assert response.status_code == 200
```

## Mocking External Services

### Mocking OPA

```python
@pytest.fixture
def mock_opa_service():
    mock = AsyncMock()
    mock.check_user_exists.return_value = True
    mock.get_user_context.return_value = {
        "user_id": "test-user-id",
        "role": "admin",
        "organization": "testorg",
        "is_org_admin": 1,
    }
    mock.get_user_permissions.return_value = {
        "projects": {"read": True, "write": True, "delete": True},
    }
    return mock
```

### Mocking Redis

```python
@pytest.fixture
def mock_session_service():
    mock = AsyncMock()
    mock.store_login_state.return_value = True
    mock.get_login_state.return_value = {
        "platform": "mlops",
        "org_name": "testorg",
    }
    return mock
```

### Mocking Okta

```python
@pytest.fixture
def mock_okta_response():
    with patch("app.services.sso_service.exchange_code_for_tokens") as mock:
        mock.return_value = {
            "id_token": "mock-id-token",
            "access_token": "mock-access-token",
        }
        yield mock
```

## Coverage Report

### Generate Coverage Report

```bash
# Generate HTML coverage report
pytest --cov=app --cov-report=html

# Open report
open htmlcov/index.html  # Mac
xdg-open htmlcov/index.html  # Linux
```

### Coverage Targets

| Component | Target Coverage |
|-----------|-----------------|
| Routers | 90% |
| Services | 85% |
| Core | 95% |
| Overall | 85% |

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd v2/auth-server
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          cd v2/auth-server
          pytest --cov=app --cov-report=xml -v
        env:
          SECRET_KEY: test-secret-key
          OKTA_DOMAIN: test.okta.com
          OKTA_ISSUER: https://test.okta.com/oauth2/default
          OKTA_CLIENT_ID: test-client-id
          OKTA_CLIENT_SECRET: test-client-secret
          REDIRECT_URI: http://localhost:8000/api/v1/auth/callback
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## Writing New Tests

### Test Naming Convention

```python
# test_{component}.py

class Test{Endpoint/Service}:
    def test_{action}_{scenario}(self):
        """Test {description}"""
        pass

# Examples:
def test_login_success(self):
def test_login_invalid_platform(self):
def test_authorize_denied(self):
def test_refresh_expired_token(self):
```

### Test Template

```python
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


class TestMyFeature:
    """Tests for my feature"""

    def test_happy_path(self, client, valid_access_token):
        """Test normal successful operation"""
        response = client.post(
            "/api/v1/endpoint",
            json={"key": "value"},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_validation_error(self, client, valid_access_token):
        """Test with invalid input"""
        response = client.post(
            "/api/v1/endpoint",
            json={},  # Missing required fields
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        
        assert response.status_code == 422

    def test_unauthorized(self, client):
        """Test without authentication"""
        response = client.post(
            "/api/v1/endpoint",
            json={"key": "value"},
        )
        
        assert response.status_code == 401 or response.status_code == 403
```

## Debugging Tests

### Run with Debug Output

```bash
# Show print statements
pytest -s

# Show local variables on failure
pytest -l

# Drop into debugger on failure
pytest --pdb

# Verbose + show locals
pytest -vl
```

### Common Issues

**1. Import Errors**
```bash
# Ensure you're in the right directory
cd v2/auth-server
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

**2. Async Test Errors**
```python
# Mark async tests with pytest.mark.asyncio
@pytest.mark.asyncio
async def test_async_function(self):
    result = await some_async_function()
    assert result is not None
```

**3. Environment Variable Errors**
```python
# Set in conftest.py before imports
import os
os.environ["SECRET_KEY"] = "test-key"
```
