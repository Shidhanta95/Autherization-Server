# User Management System v2

A comprehensive authentication and authorization system for multi-platform, multi-tenant applications.

## Quick Links

| Document | Description | Audience |
|----------|-------------|----------|
| [Architecture](./architecture.md) | System architecture and component overview | All |
| [User Flows](./user-flows.md) | Authentication and authorization flows | All |
| [API Reference](./api-reference.md) | Complete API documentation | Developers |
| [Integration Guide](./integration-guide.md) | How to integrate with your services | Developers |
| [User Initialization](./user-initialization.md) | How to create orgs, roles, and users | DevOps/Admin |
| [Testing Guide](./testing.md) | How to run and write tests | Developers |
| [Configuration](./configuration.md) | Environment variables and settings | DevOps |
| [Operations](./operations.md) | Operational procedures and troubleshooting | DevOps |
| [Glossary](./glossary.md) | Terms and definitions | All |

## Executive Summary

### What is this system?

The User Management System provides secure **authentication** and **authorization** for our platform suite. It enables:

- **Single Sign-On (SSO)** - Users authenticate once using their corporate credentials (via Okta, Azure AD, etc.)
- **Role-Based Access Control (RBAC)** - Fine-grained permissions based on user roles within their organization
- **Multi-Platform Support** - Supports multiple platforms (MLOps, Analytics, Vision, DC) with isolated access control
- **Multi-Tenant Architecture** - Each organization's data and permissions are isolated

### Key Capabilities

| Capability | Description |
|------------|-------------|
| **SSO Authentication** | Integration with enterprise identity providers (Keycloak, Okta, Azure AD, Auth0) |
| **Identity Brokering** | Keycloak acts as Identity Broker for federated SSO with multiple IdPs |
| **JWT Tokens** | Secure, stateless authentication tokens |
| **RBAC Permissions** | Granular read/write/delete permissions per resource |
| **Real-time Sync** | Permission changes propagate within seconds via CDC |
| **License Enforcement** | Feature access tied to license terms |

### Business Value

1. **Security** - Enterprise-grade authentication with industry standards (OAuth 2.0, OIDC)
2. **Compliance** - Audit-ready permission tracking and access control
3. **User Experience** - Single sign-on means no separate credentials to manage
4. **Flexibility** - Per-organization customization of roles and permissions
5. **Scalability** - Handles thousands of users across multiple platforms

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Identity Provider (one of):
  - **Keycloak** (included in docker-compose for development)
  - Okta account
  - Azure AD
  - Auth0

### Running the System

```bash
# Navigate to v2 directory
cd v2

# Start all services (includes Keycloak)
docker-compose up -d

# Wait for services to be healthy (especially Keycloak ~60s)
docker-compose ps

# Check status
docker-compose ps
```

### Verifying the Setup

```bash
# Health check
curl http://localhost:8000/health

# View API docs
open http://localhost:8000/docs

# Keycloak Admin Console (admin/admin)
open http://localhost:8080/admin
```

### Default Test Users (Keycloak)

| Email | Password | Role |
|-------|----------|------|
| `testuser@acme.com` | `testpassword123` | viewer |
| `admin@acme.com` | `adminpassword123` | admin |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENTS                                  │
│                  (Web App, Mobile, Services)                     │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AUTH SERVER                                 │
│                                                                 │
│  POST /login      → Get IdP login URL                          │
│  GET  /callback   → Exchange code, return JWT                   │
│  POST /refresh    → Get new access token                        │
│  POST /authorize  → Check permission                            │
└──────────────┬────────────────────────────┬─────────────────────┘
               │                            │
               ▼                            ▼
┌──────────────────────────────┐  ┌───────────────────────────────┐
│         KEYCLOAK             │  │              OPA               │
│     (Identity Broker)        │  │      (Policy Engine)           │
│                              │  │                                │
│  ┌────────────────────────┐  │  │  - Permission checks           │
│  │   Native Users         │  │  │  - Role-based access control   │
│  │   (username/password)  │  │  └──────────────┬────────────────┘
│  └────────────────────────┘  │                 │
│                              │                 ▼
│  ┌────────────────────────┐  │  ┌───────────────────────────────┐
│  │   Federated IdPs       │  │  │          PostgreSQL           │
│  │   - Okta               │  │  │       (RBAC Database)         │
│  │   - Azure AD           │  │  │                               │
│  │   - Auth0              │  │  │  - Organizations              │
│  └────────────────────────┘  │  │  - Roles & Permissions        │
└──────────────────────────────┘  │  - User Assignments           │
                                  └───────────────────────────────┘
```

## Support

For issues or questions:
- Check the [Troubleshooting](./operations.md#troubleshooting) guide
- Review [Glossary](./glossary.md) for terminology
- Contact the platform team
