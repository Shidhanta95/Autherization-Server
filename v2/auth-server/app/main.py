"""
Auth Server - Main FastAPI Application

Provides authentication and authorization services:
- SSO login via Okta/OIDC
- JWT token management (access + refresh)
- Authorization endpoint for permission checks
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db import init_pool, close_pool
from app.routers import auth_router, authorize_router, manage_router
from app.services import session_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Startup: Initialize connections
    Shutdown: Close connections
    """
    # Startup
    print("[AUTH] Starting Auth Server...")
    await init_pool()
    print("[AUTH] Database pool initialised")
    yield
    # Shutdown
    print("[AUTH] Shutting down Auth Server...")
    await close_pool()
    await session_service.close()


app = FastAPI(
    title="Auth Server",
    description="""
## Authentication & Authorization Server

This API provides:
- **SSO Authentication** via Okta/OIDC identity providers
- **JWT Token Management** with access and refresh tokens
- **Authorization Checks** via OPA (Open Policy Agent)

### Authentication Flow
1. `POST /api/v1/auth/login` - Get IdP login URL
2. User authenticates with IdP
3. `GET /api/v1/auth/callback` - Exchange code for tokens
4. `POST /api/v1/auth/refresh` - Refresh access token
5. `POST /api/v1/auth/logout` - Revoke refresh token

### Authorization
- `POST /api/v1/authorize` - Check if user can perform action
- `GET /api/v1/authorize/me` - Get current user info

### Management (Org Admin required)
- `GET/POST /api/v1/manage/orgs` - Organization CRUD
- `GET/POST /api/v1/manage/orgs/{id}/roles` - Role CRUD
- `PUT /api/v1/manage/orgs/{id}/roles/{id}/permissions` - Permission management
- `GET/POST /api/v1/manage/orgs/{id}/users` - User management
- `GET /api/v1/manage/audit` - Audit log
    """,
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(authorize_router)
app.include_router(manage_router)


@app.get("/", tags=["Health"])
def root():
    """Root endpoint - health check"""
    return {
        "service": "Auth Server",
        "version": "2.0.0",
        "status": "running",
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint for container orchestration"""
    return {
        "status": "healthy",
        "service": "auth-server",
    }
