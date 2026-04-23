# API Reference

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication Endpoints

### POST /auth/login

Initiate SSO login flow.

**Request Body:**
```json
{
  "platform": "mlops",
  "org_name": "cloudangles"
}
```

**Response (200 OK):**
```json
{
  "login_url": "https://dev-123456.okta.com/oauth2/v1/authorize?client_id=...&response_type=code&..."
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 400 | Invalid platform |
| 404 | SSO not configured for organization |
| 500 | Failed to initialize session |

---

### GET /auth/callback

Handle IdP callback after authentication.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| code | string | Authorization code from IdP |
| state | string | State parameter for CSRF validation |

**Response (200 OK):**
```json
{
  "success": true,
  "email": "user@example.com",
  "organization": "cloudangles",
  "user_id": "471ab5e9-b8e5-4dd6-a8f8-9d387ff4081c",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "message": "Successfully logged in via SSO"
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 400 | Invalid/expired state, missing tokens |
| 401 | Invalid ID token |
| 403 | User not registered in system |

---

### POST /auth/refresh

Exchange refresh token for new access token.

**Request Body:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 401 | Invalid/revoked/expired refresh token |
| 401 | User no longer exists in the system (refresh token is also revoked) |
| 403 | User no longer has platform access |

---

### POST /auth/logout

Revoke refresh token.

**Request Body:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

> **Note:** `refresh_token` is optional. If omitted, the server acknowledges the logout without revoking any token.

**Response (200 OK) — token provided and revoked:**
```json
{
  "success": true,
  "message": "Successfully logged out"
}
```

**Response (200 OK) — token provided but revocation failed:**
```json
{
  "success": false,
  "message": "Failed to revoke token (may already be revoked)"
}
```

**Response (200 OK) — no token provided:**
```json
{
  "success": true,
  "message": "Logged out (no token provided to revoke)"
}
```

---

## Authorization Endpoints

### POST /authorize

Check if user is authorized for an action.

**Headers:**
```
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "resource": "projects",
  "action": "write",
  "context": {
    "project_id": "uuid-123"
  }
}
```

**Response (200 OK):**
```json
{
  "allowed": true,
  "user_id": "471ab5e9-b8e5-4dd6-a8f8-9d387ff4081c",
  "organization": "cloudangles",
  "role": "admin",
  "is_org_admin": 1
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 401 | Invalid/expired access token |

---

### GET /authorize/me

Get current user information from JWT.

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "email": "user@example.com",
  "user_id": "471ab5e9-b8e5-4dd6-a8f8-9d387ff4081c",
  "organization": "cloudangles",
  "platform": "mlops",
  "is_org_admin": 1,
  "permissions": {
    "projects": {"read": true, "write": true, "delete": true},
    "pipelines": {"read": true, "write": false, "delete": false},
    "global_access": true,
    "bu_access": false
  }
}
```

---

### POST /authorize/batch

Check multiple permissions at once.

**Headers:**
```
Authorization: Bearer <access_token>
```

**Request Body:**
```json
[
  {"resource": "projects", "action": "read"},
  {"resource": "projects", "action": "write"},
  {"resource": "pipelines", "action": "delete"}
]
```

**Response (200 OK):**
```json
{
  "user_id": "471ab5e9-b8e5-4dd6-a8f8-9d387ff4081c",
  "organization": "cloudangles",
  "results": [
    {"resource": "projects", "action": "read", "allowed": true},
    {"resource": "projects", "action": "write", "allowed": true},
    {"resource": "pipelines", "action": "delete", "allowed": false}
  ]
}
```

---

## Health Endpoints

### GET /

Root endpoint.

**Response (200 OK):**
```json
{
  "service": "Auth Server",
  "version": "2.0.0",
  "status": "running"
}
```

### GET /health

Health check for orchestration.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "auth-server"
}
```

---

## JWT Token Structure

### Access Token Claims

```json
{
  "email": "user@example.com",
  "userID": "471ab5e9-b8e5-4dd6-a8f8-9d387ff4081c",
  "organization": "cloudangles",
  "platform": "mlops",
  "org_admin": 1,
  "permissions": {
    "projects": {"read": true, "write": true, "delete": true},
    "pipelines": {"read": true, "write": false, "delete": false},
    "global_access": true,
    "bu_access": false
  },
  "licence": {
    "instanceid": "...",
    "organization": "cloudangles",
    "License": {...},
    "Properties": {...},
    "MaxUsers": 100,
    "MaxBUs": 50
  },
  "iat": 1773126065,
  "exp": 1773129665,
  "type": "access"
}
```

### Refresh Token Claims

```json
{
  "email": "user@example.com",
  "platform": "mlops",
  "jti": "unique-token-id",
  "iat": 1773126065,
  "exp": 1775718065,
  "type": "refresh"
}
```

---

## Error Response Format

All errors follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

## Test Endpoint (Development Only)

### POST /auth/test-login

Bypass SSO for testing. Only available when `DEBUG=true`.

**Request Body:**
```json
{
  "platform": "mlops",
  "org_name": "acme",
  "email": "testuser@acme.com"
}
```

**Response (200 OK):**

Same as [GET /auth/callback](#get-authcallback) response.

**Errors:**
| Status | Description |
|--------|-------------|
| 400 | Invalid platform |
| 403 | User not registered in system |
| 403 | User has no access to platform |
| 404 | Endpoint not available (DEBUG is false) |

---

## Management Endpoints

All management endpoints are under `/api/v1/manage` and require a valid JWT with `is_org_admin: 1`. The platform is taken from the caller's JWT.

### Organizations

#### GET /manage/orgs

List all organizations for the caller's platform.

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "orgs": [
    {"id": "uuid-123", "name": "acme"}
  ],
  "total": 1
}
```

---

#### POST /manage/orgs

Create a new organization.

**Headers:**
```
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "name": "acme"
}
```

**Response (201 Created):**
```json
{
  "id": "uuid-123",
  "name": "acme"
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 403 | Not an org admin |
| 409 | Organization name already exists |

---

#### GET /manage/orgs/{org_id}

Get a single organization.

**Response (200 OK):**
```json
{
  "id": "uuid-123",
  "name": "acme"
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | Organization not found |

---

#### PUT /manage/orgs/{org_id}

Update an organization's name.

**Request Body:**
```json
{
  "name": "new-name"
}
```

**Response (200 OK):**
```json
{
  "id": "uuid-123",
  "name": "new-name"
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | Organization not found |
| 409 | Duplicate organization name |

---

#### DELETE /manage/orgs/{org_id}

Delete an organization. Fails if the org still has roles.

**Response:** `204 No Content`

**Errors:**
| Status | Description |
|--------|-------------|
| 409 | Organization still has roles — remove all roles first |

---

### Roles

#### GET /manage/orgs/{org_id}/roles

List all roles in an organization.

**Response (200 OK):**
```json
{
  "roles": [
    {"id": "uuid-456", "name": "admin", "global_access": true, "bu_access": false, "org_name": "acme"}
  ],
  "total": 1
}
```

---

#### POST /manage/orgs/{org_id}/roles

Create a new role.

**Request Body:**
```json
{
  "name": "editor",
  "global_access": false,
  "bu_access": true
}
```

**Response (201 Created):**
```json
{
  "id": "uuid-456",
  "name": "editor",
  "global_access": false,
  "bu_access": true,
  "org_name": "acme"
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | Organization not found |
| 409 | Role name already exists in this organization |

---

#### GET /manage/orgs/{org_id}/roles/{role_id}

Get role details including all permissions.

**Response (200 OK):**
```json
{
  "id": "uuid-456",
  "name": "editor",
  "global_access": false,
  "bu_access": true,
  "org_name": "acme",
  "permissions": [
    {"resource": "projects", "can_read": true, "can_write": true, "can_delete": false}
  ]
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | Role not found |

---

#### PUT /manage/orgs/{org_id}/roles/{role_id}

Update a role. Supports partial updates — all fields are optional.

**Request Body:**
```json
{
  "name": "senior-editor",
  "global_access": true
}
```

**Response (200 OK):**
```json
{
  "id": "uuid-456",
  "name": "senior-editor",
  "global_access": true,
  "bu_access": true,
  "org_name": "acme"
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 400 | No fields to update |
| 404 | Role not found |
| 409 | Duplicate role name in this organization |

---

#### DELETE /manage/orgs/{org_id}/roles/{role_id}

Delete a role. Fails if the role still has users assigned.

**Response:** `204 No Content`

**Errors:**
| Status | Description |
|--------|-------------|
| 409 | Role still has users — reassign or remove all users first |

---

### Permissions

#### GET /manage/orgs/{org_id}/roles/{role_id}/permissions

Get all permissions for a role.

**Response (200 OK):**
```json
{
  "role_name": "editor",
  "org_name": "acme",
  "permissions": [
    {"resource": "projects", "can_read": true, "can_write": true, "can_delete": false}
  ],
  "total": 1
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | Role not found |

---

#### PUT /manage/orgs/{org_id}/roles/{role_id}/permissions

Bulk set permissions for a role. Upserts — existing resources are updated, new ones created.

**Request Body:**
```json
{
  "permissions": [
    {"resource": "projects", "can_read": true, "can_write": true, "can_delete": false},
    {"resource": "pipelines", "can_read": true, "can_write": false, "can_delete": false}
  ]
}
```

**Response (200 OK):**
```json
{
  "role_name": "editor",
  "org_name": "acme",
  "permissions": [
    {"resource": "pipelines", "can_read": true, "can_write": false, "can_delete": false},
    {"resource": "projects", "can_read": true, "can_write": true, "can_delete": false}
  ],
  "total": 2
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | Role not found in this organization |

---

#### DELETE /manage/orgs/{org_id}/roles/{role_id}/permissions/{resource}

Revoke all permissions on a resource for a role.

**Response:** `204 No Content`

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | Permission not found for this role and resource |

---

### Users

#### GET /manage/orgs/{org_id}/users

List all users in an organization.

**Response (200 OK):**
```json
{
  "users": [
    {
      "id": "uuid-789",
      "email": "jane@acme.com",
      "user_uid": "okta-uid-12345",
      "role_name": "editor",
      "org_name": "acme",
      "is_org_admin": false
    }
  ],
  "total": 1
}
```

---

#### POST /manage/orgs/{org_id}/users

Add a user to an organization with a specific role.

**Request Body:**
```json
{
  "email": "jane@acme.com",
  "role_name": "editor",
  "user_uid": "okta-uid-12345",
  "is_org_admin": false
}
```

**Response (201 Created):**
```json
{
  "id": "uuid-789",
  "email": "jane@acme.com",
  "user_uid": "okta-uid-12345",
  "role_name": "editor",
  "org_name": "acme",
  "is_org_admin": false
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | Organization or role not found |
| 409 | User email already exists in this platform |

---

#### GET /manage/orgs/{org_id}/users/{user_id}

Get a single user.

**Response (200 OK):**
```json
{
  "id": "uuid-789",
  "email": "jane@acme.com",
  "user_uid": "okta-uid-12345",
  "role_name": "editor",
  "org_name": "acme",
  "is_org_admin": false
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | User not found |

---

#### PUT /manage/orgs/{org_id}/users/{user_id}

Update a user's role or org admin status. Supports partial updates.

**Request Body:**
```json
{
  "role_name": "admin",
  "is_org_admin": true
}
```

**Response (200 OK):**
```json
{
  "id": "uuid-789",
  "email": "jane@acme.com",
  "user_uid": "okta-uid-12345",
  "role_name": "admin",
  "org_name": "acme",
  "is_org_admin": true
}
```

**Errors:**
| Status | Description |
|--------|-------------|
| 400 | No fields to update |
| 404 | User or role not found |

---

#### DELETE /manage/orgs/{org_id}/users/{user_id}

Remove a user from the organization.

**Response:** `204 No Content`

**Errors:**
| Status | Description |
|--------|-------------|
| 404 | User not found |

---

### Audit Log

#### GET /manage/audit

Query the audit log for the caller's platform.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| org_name | string | null | Filter by organization name |
| limit | int | 50 | Max entries (1–200) |
| offset | int | 0 | Pagination offset |

**Response (200 OK):**
```json
{
  "entries": [
    {
      "id": "uuid-entry",
      "timestamp": "2026-04-23T12:00:00Z",
      "actor_email": "admin@acme.com",
      "platform": "mlops",
      "org_name": "acme",
      "action": "create_role",
      "target_type": "role",
      "target_id": "uuid-456",
      "details": {"name": "editor"}
    }
  ],
  "total": 1
}
```

---

## Rate Limiting

Currently no rate limiting is implemented. For production, consider adding rate limits:

| Endpoint | Suggested Limit |
|----------|-----------------|
| /auth/login | 10/minute/IP |
| /auth/refresh | 30/minute/user |
| /authorize | 100/minute/user |
| /manage/* | 30/minute/user |
