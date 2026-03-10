# Glossary

Definitions of key terms and concepts used in the User Management System.

## Authentication & Authorization

| Term | Definition |
|------|------------|
| **Authentication (AuthN)** | The process of verifying a user's identity. "Who are you?" |
| **Authorization (AuthZ)** | The process of verifying what a user can do. "What can you do?" |
| **Identity Provider (IdP)** | External service that authenticates users (e.g., Okta, Azure AD) |
| **Single Sign-On (SSO)** | Authentication scheme allowing users to log in once and access multiple applications |

## OAuth & OIDC

| Term | Definition |
|------|------------|
| **OAuth 2.0** | Industry-standard authorization framework for token-based access |
| **OpenID Connect (OIDC)** | Identity layer on top of OAuth 2.0 for authentication |
| **Authorization Code** | Temporary code exchanged for tokens in OAuth flow |
| **Access Token** | Short-lived token granting access to resources |
| **Refresh Token** | Long-lived token used to obtain new access tokens |
| **ID Token** | JWT containing user identity claims from the IdP |
| **State Parameter** | Random value for CSRF protection in OAuth flow |
| **Nonce** | Random value for replay attack protection in OIDC |

## JWT (JSON Web Token)

| Term | Definition |
|------|------------|
| **JWT** | Compact, URL-safe token format for transmitting claims |
| **Claims** | Statements about the user (e.g., email, permissions) |
| **JTI (JWT ID)** | Unique identifier for a specific token |
| **iat (Issued At)** | Timestamp when the token was created |
| **exp (Expiration)** | Timestamp when the token expires |
| **Signature** | Cryptographic signature verifying token integrity |

## RBAC (Role-Based Access Control)

| Term | Definition |
|------|------------|
| **RBAC** | Access control model based on user roles |
| **Role** | Named collection of permissions (e.g., "admin", "developer") |
| **Permission** | Specific action allowed on a resource (e.g., "read projects") |
| **Resource** | Entity being protected (e.g., "projects", "pipelines") |
| **Action** | Operation on a resource (read, write, delete) |

## Multi-Tenancy

| Term | Definition |
|------|------------|
| **Tenant** | An organization/customer with isolated data and access |
| **Organization** | Same as tenant - a customer entity |
| **Platform** | A product/application (MLOps, Analytics, etc.) |
| **Org Admin** | Administrator for a specific organization |
| **Global Access** | Permission to access all resources across business units |
| **BU Access** | Permission limited to specific business units |

## Infrastructure

| Term | Definition |
|------|------------|
| **OPA (Open Policy Agent)** | Policy engine for authorization decisions |
| **Rego** | Policy language used by OPA |
| **CDC (Change Data Capture)** | Pattern for tracking database changes |
| **Debezium** | CDC platform that streams database changes |
| **Kafka** | Distributed event streaming platform |
| **WAL (Write-Ahead Log)** | PostgreSQL transaction log used for CDC |

## Architecture

| Term | Definition |
|------|------------|
| **Stateless** | Service that doesn't store session data locally |
| **Microservice** | Small, independent service with specific responsibility |
| **Sidecar** | Helper container that runs alongside main application |
| **Bundle** | Package of data/policies pushed to OPA |
| **Hot Reload** | Updating configuration without service restart |

## Security

| Term | Definition |
|------|------------|
| **CSRF** | Cross-Site Request Forgery attack |
| **XSS** | Cross-Site Scripting attack |
| **Token Revocation** | Invalidating a token before expiry |
| **MFA** | Multi-Factor Authentication |
| **HTTPS** | HTTP over TLS/SSL encryption |

## API

| Term | Definition |
|------|------------|
| **REST** | Representational State Transfer architectural style |
| **Endpoint** | URL path that accepts API requests |
| **Bearer Token** | Token passed in Authorization header |
| **HTTP Status Codes** | Standard response codes (200=OK, 401=Unauthorized, etc.) |

## Common Abbreviations

| Abbreviation | Full Form |
|--------------|-----------|
| API | Application Programming Interface |
| DB | Database |
| HA | High Availability |
| JWT | JSON Web Token |
| OIDC | OpenID Connect |
| OPA | Open Policy Agent |
| RBAC | Role-Based Access Control |
| SSO | Single Sign-On |
| TTL | Time To Live |
| UUID | Universally Unique Identifier |
| WAL | Write-Ahead Log |

## Related Standards

| Standard | Description |
|----------|-------------|
| RFC 6749 | OAuth 2.0 Authorization Framework |
| RFC 6750 | OAuth 2.0 Bearer Token Usage |
| RFC 7519 | JSON Web Token (JWT) |
| OpenID Connect Core | OIDC specification |

## Example Scenarios

### "User has read permission on projects"
- **User**: Identity (email@example.com)
- **Permission**: read
- **Resource**: projects
- **Check**: Does user's role grant read access to projects?

### "Token expired"
- The JWT's `exp` claim timestamp is in the past
- User must obtain a new token (via refresh or re-login)

### "Session invalid"
- The login state in Redis has expired (>10 min)
- User must restart the login flow

### "User not in tenant"
- User authenticated with IdP but not provisioned in our database
- Admin must add user via SQL functions
