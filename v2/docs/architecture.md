# System Architecture

## Overview

The User Management System is built on a modern, microservices architecture designed for scalability, security, and real-time responsiveness.

## High-Level Architecture

```mermaid
graph TB
    subgraph Clients
        WebApp[Web Application]
        Mobile[Mobile App]
        Services[Backend Services]
    end

    subgraph "Auth Server"
        API[FastAPI Application]
        AuthRouter[Auth Router]
        AuthzRouter[Authorize Router]
    end

    subgraph "External IdP"
        Okta[Okta / Azure AD]
    end

    subgraph "Policy Engine"
        OPA[Open Policy Agent]
    end

    subgraph "Data Layer"
        PG[(PostgreSQL)]
        Redis[(Redis)]
    end

    subgraph "CDC Pipeline"
        Debezium[Debezium]
        Kafka[Kafka]
        SyncWorker[Sync Worker]
    end

    WebApp --> API
    Mobile --> API
    Services --> API

    API --> AuthRouter
    API --> AuthzRouter

    AuthRouter --> Okta
    AuthRouter --> OPA
    AuthRouter --> Redis

    AuthzRouter --> OPA

    Debezium --> PG
    Debezium --> Kafka
    Kafka --> SyncWorker
    SyncWorker --> OPA
    SyncWorker --> PG
```

## Component Details

### 1. Auth Server (FastAPI)

The central authentication and authorization service.

| Component | Purpose |
|-----------|---------|
| **Auth Router** | Handles login, callback, refresh, logout |
| **Authorize Router** | Handles permission checks |
| **Token Service** | JWT creation and validation |
| **Session Service** | Redis-based session management |
| **OPA Service** | Queries OPA for authorization |
| **SSO Service** | OIDC/OAuth flow with IdP |

**Technology:** Python 3.11, FastAPI, Pydantic

### 2. Identity Provider (Okta)

External identity provider for user authentication.

| Responsibility | Description |
|----------------|-------------|
| User Authentication | Validates user credentials |
| MFA | Multi-factor authentication |
| SSO | Single sign-on across applications |
| User Directory | Source of truth for user identity |

**Protocol:** OAuth 2.0 / OpenID Connect

### 3. Open Policy Agent (OPA)

Policy decision point for authorization.

| Responsibility | Description |
|----------------|-------------|
| Permission Checks | Evaluates if user can perform action |
| Policy Enforcement | Enforces RBAC rules |
| Data Store | Holds synced user/permission data |

**Policy Language:** Rego

### 4. PostgreSQL Database

Persistent storage for RBAC data.

| Table Pattern | Contents |
|---------------|----------|
| `{platform}_orgs` | Organizations/tenants |
| `{platform}_roles` | Role definitions |
| `{platform}_perms` | Resource permissions |
| `{platform}_users` | User assignments |

**Features:** WAL for CDC, UUID primary keys

### 5. Redis

In-memory data store for sessions.

| Use Case | TTL |
|----------|-----|
| Login State | 10 minutes |
| Refresh Tokens | 30 days |
| Revoked Tokens | Until original expiry |

### 6. CDC Pipeline (Debezium + Kafka)

Real-time data synchronization from PostgreSQL to OPA.

```mermaid
sequenceDiagram
    participant Admin
    participant PostgreSQL
    participant Debezium
    participant Kafka
    participant SyncWorker
    participant OPA

    Admin->>PostgreSQL: UPDATE user role
    PostgreSQL->>Debezium: WAL change event
    Debezium->>Kafka: Publish to topic
    Kafka->>SyncWorker: Consume message
    SyncWorker->>PostgreSQL: Fetch updated bundle
    SyncWorker->>OPA: Push new data
    Note over OPA: Permissions updated<br/>~2-5 seconds total
```

## Data Flow

### Authentication Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant AuthServer
    participant IdP as Okta
    participant OPA
    participant Redis

    User->>Frontend: Click Login
    Frontend->>AuthServer: POST /login {platform, org}
    AuthServer->>Redis: Store state
    AuthServer->>Frontend: Return IdP URL
    Frontend->>IdP: Redirect to login
    User->>IdP: Enter credentials
    IdP->>Frontend: Redirect with code
    Frontend->>AuthServer: GET /callback?code=...
    AuthServer->>IdP: Exchange code for tokens
    IdP->>AuthServer: Return ID token
    AuthServer->>OPA: Check user exists
    AuthServer->>OPA: Get permissions
    AuthServer->>Redis: Store refresh token
    AuthServer->>Frontend: Return JWT tokens
    Frontend->>User: Logged in!
```

### Authorization Flow

```mermaid
sequenceDiagram
    participant Service
    participant AuthServer
    participant OPA

    Service->>AuthServer: POST /authorize<br/>{resource, action}<br/>+ JWT
    AuthServer->>AuthServer: Validate JWT
    AuthServer->>OPA: Query permission
    OPA->>OPA: Evaluate policy
    OPA->>AuthServer: allowed: true/false
    AuthServer->>Service: Authorization response
```

## Security Architecture

### Token Security

| Token Type | Lifetime | Storage | Contains |
|------------|----------|---------|----------|
| Access Token | 1 hour | Client memory | User info, permissions |
| Refresh Token | 30 days | Redis + Client | User email, platform |
| ID Token | N/A (from IdP) | Not stored | Identity claims |

### Security Measures

1. **HTTPS** - All communication encrypted in transit
2. **JWT Signing** - Tokens signed with HS256
3. **State Parameter** - CSRF protection in OAuth flow
4. **Token Revocation** - Refresh tokens can be revoked
5. **Short Expiry** - Access tokens expire in 1 hour

## Scalability

### Horizontal Scaling

| Component | Scaling Strategy |
|-----------|------------------|
| Auth Server | Stateless, scale with load balancer |
| OPA | Replicate with synced data |
| Redis | Redis Cluster for HA |
| PostgreSQL | Read replicas for queries |

### Performance Considerations

- JWT validation is local (no network call)
- OPA queries are fast (~1-5ms)
- Redis operations are sub-millisecond
- CDC provides eventual consistency (~2-5s)

## Disaster Recovery

| Component | Recovery Strategy |
|-----------|-------------------|
| PostgreSQL | Point-in-time recovery, replicas |
| Redis | Persistence + replicas |
| OPA | Stateless, re-sync from PostgreSQL |
| Auth Server | Stateless, redeploy |
