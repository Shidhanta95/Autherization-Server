# User Flows

Visual diagrams of the main user flows in the system.

## 1. Login Flow

### Overview

```mermaid
graph LR
    A[User] --> B[Frontend]
    B --> C[Auth Server]
    C --> D[IdP/Okta]
    D --> E[User Authenticates]
    E --> F[Callback]
    F --> G[JWT Issued]
    G --> H[User Logged In]
```

### Detailed Flow

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant F as Frontend
    participant A as Auth Server
    participant R as Redis
    participant I as IdP (Okta)
    participant O as OPA

    Note over U,F: Step 1: User initiates login
    U->>F: Click "Login"
    F->>F: Select platform & org

    Note over F,A: Step 2: Get IdP URL
    F->>A: POST /login<br/>{platform: "mlops", org_name: "cloudangles"}
    A->>A: Validate platform
    A->>A: Generate state (UUID)
    A->>R: Store state → {platform, org}
    A->>F: {login_url: "https://okta.com/..."}

    Note over F,I: Step 3: Redirect to IdP
    F->>I: Redirect to login_url
    U->>I: Enter username/password
    I->>I: Authenticate user
    I->>I: MFA (if enabled)

    Note over I,F: Step 4: IdP callback
    I->>F: Redirect to callback?code=xyz&state=abc

    Note over F,A: Step 5: Exchange code
    F->>A: GET /callback?code=xyz&state=abc
    A->>R: Lookup state → {platform, org}
    A->>I: POST /token (exchange code)
    I->>A: {id_token, access_token}
    A->>A: Verify ID token signature
    A->>A: Extract email from claims

    Note over A,O: Step 6: Authorization check
    A->>O: Check user exists?
    O->>A: Yes
    A->>O: Get user context
    O->>A: {user_id, org, role}
    A->>O: Get permissions
    O->>A: {projects: {r,w,d}, ...}

    Note over A,F: Step 7: Issue tokens
    A->>A: Create access token (1hr)
    A->>R: Store refresh token (30d)
    A->>A: Create refresh token
    A->>R: Delete login state
    A->>F: {access_token, refresh_token, ...}

    Note over F,U: Step 8: Complete
    F->>F: Store tokens
    F->>U: Show logged-in state
```

## 2. Token Refresh Flow

### When to Refresh

- Access token expires (1 hour)
- Before token expiry (proactive refresh)
- After 401 response (reactive refresh)

### Flow Diagram

```mermaid
sequenceDiagram
    autonumber
    participant F as Frontend
    participant A as Auth Server
    participant R as Redis
    participant O as OPA

    Note over F: Access token about to expire

    F->>A: POST /refresh<br/>{refresh_token: "..."}
    
    A->>A: Validate refresh token
    A->>A: Check token type = "refresh"
    A->>R: Check if token revoked
    R->>A: Not revoked
    A->>R: Check token exists
    R->>A: Token valid

    Note over A,O: Get fresh permissions
    A->>O: Check user still exists
    O->>A: Yes
    A->>O: Get current permissions
    O->>A: {permissions}

    A->>A: Create new access token
    A->>F: {access_token, refresh_token, expires_in}

    F->>F: Update stored tokens
```

## 3. Authorization Check Flow

### From Frontend

```mermaid
sequenceDiagram
    participant F as Frontend
    participant A as Auth Server
    participant O as OPA

    F->>A: POST /authorize<br/>Authorization: Bearer <token><br/>{resource: "projects", action: "delete"}
    
    A->>A: Validate JWT
    A->>A: Extract email, platform
    
    A->>O: POST /v1/data/authz/allow<br/>{user, platform, resource, action}
    O->>O: Evaluate policy
    O->>A: {result: true}
    
    A->>F: {allowed: true, user_id, org, role}
```

### From Backend Service

```mermaid
sequenceDiagram
    participant S as Backend Service
    participant A as Auth Server
    participant O as OPA

    Note over S: User request with JWT

    S->>A: GET /authorize/me<br/>Authorization: Bearer <token>
    A->>A: Validate JWT
    A->>S: {email, user_id, permissions, ...}

    S->>S: Check permissions locally
    alt Has permission
        S->>S: Process request
    else No permission
        S->>S: Return 403
    end
```

## 4. Logout Flow

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant A as Auth Server
    participant R as Redis

    U->>F: Click "Logout"
    
    F->>A: POST /logout<br/>{refresh_token: "..."}
    A->>A: Decode refresh token
    A->>A: Get JTI (token ID)
    A->>R: Add to revocation list
    A->>R: Delete from token store
    A->>F: {success: true}

    F->>F: Clear local storage
    F->>U: Redirect to login
```

## 5. Permission Change Flow

### What happens when admin changes user permissions

```mermaid
sequenceDiagram
    participant Admin
    participant DB as PostgreSQL
    participant D as Debezium
    participant K as Kafka
    participant SW as Sync Worker
    participant O as OPA
    participant U as User

    Admin->>DB: UPDATE role permissions
    
    Note over DB,D: CDC captures change
    DB->>D: WAL event
    D->>K: Publish to topic

    Note over K,SW: Sync worker processes
    K->>SW: Consume message
    SW->>DB: Fetch updated bundle
    SW->>O: PUT /v1/data/rbac

    Note over O: ~2-5 seconds total

    Note over U: User's next request
    U->>U: Access token still has old permissions
    
    Note over U: But /authorize checks OPA
    U->>O: Permission check
    O->>U: New permission result

    Note over U: On next token refresh
    U->>U: POST /refresh
    U->>U: New token has updated permissions
```

## 6. User Registration Flow (Current: Pre-provisioned)

```mermaid
sequenceDiagram
    participant SA as Super Admin
    participant DB as PostgreSQL
    participant CDC as CDC Pipeline
    participant O as OPA
    participant U as New User

    Note over SA: Organization purchases platform access

    SA->>DB: add_org('mlops', 'newcorp')
    SA->>DB: add_role('mlops', 'newcorp', 'admin', true, false)
    SA->>DB: set_perm('mlops', 'newcorp', 'admin', 'projects', t, t, t)
    SA->>DB: add_user('mlops', 'newcorp', 'admin@newcorp.com', 'admin', 'uuid', true)

    CDC->>O: Sync changes

    Note over U: User can now login
    U->>U: POST /login
    U->>U: Complete SSO flow
    U->>U: Receive JWT with permissions
```

## 7. Multi-Platform Access

### User accessing different platforms

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant A as Auth Server
    participant O as OPA

    Note over U,F: User logged into MLOps
    U->>F: Has MLOps JWT

    Note over U,F: User wants to access Analytics
    U->>F: Switch to Analytics platform
    F->>A: POST /login<br/>{platform: "analytics", org: "cloudangles"}
    
    Note over A,O: New login flow for Analytics
    A->>O: Get Analytics permissions
    O->>A: Different permission set
    A->>F: New JWT with Analytics permissions

    Note over U: User now has two sessions
    U->>U: MLOps JWT (browser tab 1)
    U->>U: Analytics JWT (browser tab 2)
```

## Flow Summary

| Flow | Trigger | Result |
|------|---------|--------|
| **Login** | User clicks login | JWT tokens issued |
| **Refresh** | Token expiring | New access token |
| **Authorize** | Protected action | Allow/deny decision |
| **Logout** | User clicks logout | Tokens revoked |
| **Permission Change** | Admin updates role | OPA data updated |
| **User Registration** | Admin adds user | User can login |
