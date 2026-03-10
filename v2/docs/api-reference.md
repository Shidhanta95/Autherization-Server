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

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Successfully logged out"
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

## Rate Limiting

Currently no rate limiting is implemented. For production, consider adding rate limits:

| Endpoint | Suggested Limit |
|----------|-----------------|
| /auth/login | 10/minute/IP |
| /auth/refresh | 30/minute/user |
| /authorize | 100/minute/user |
