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
| **SSO Authentication** | Integration with enterprise identity providers |
| **JWT Tokens** | Secure, stateless authentication tokens |
| **RBAC Permissions** | Granular read/write/delete permissions per resource |
| **Real-time Sync** | Permission changes propagate within seconds |
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
- Okta account (or other OIDC-compatible IdP)

### Running the System

```bash
# Navigate to v2 directory
cd v2

# Configure environment
cp auth-server/.env.example auth-server/.env
# Edit .env with your Okta credentials

# Start all services
docker-compose up -d

# Check status
docker-compose ps
```

### Verifying the Setup

```bash
# Health check
curl http://localhost:8000/health

# View API docs
open http://localhost:8000/docs
```

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
┌──────────────────────────┐  ┌───────────────────────────────────┐
│     Identity Provider    │  │              OPA                   │
│     (Okta, Azure AD)     │  │      (Policy Engine)               │
│                          │  │                                    │
│  - User authentication   │  │  - Permission checks               │
│  - MFA, SSO              │  │  - Role-based access control       │
└──────────────────────────┘  └──────────────┬────────────────────┘
                                             │
                                             ▼
                              ┌───────────────────────────────────┐
                              │          PostgreSQL               │
                              │       (RBAC Database)             │
                              │                                   │
                              │  - Organizations                  │
                              │  - Roles & Permissions            │
                              │  - User Assignments               │
                              └───────────────────────────────────┘
```

## Support

For issues or questions:
- Check the [Troubleshooting](./operations.md#troubleshooting) guide
- Review [Glossary](./glossary.md) for terminology
- Contact the platform team
