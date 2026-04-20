# Authorization Server v2 — Developer Guide

A complete walkthrough of the project for anyone joining the team. This covers every component, where to find the code, what to look at in each container/database, and how data flows end-to-end.

---

## Table of Contents

1. [How to Start the System](#1-how-to-start-the-system)
2. [Containers & What They Do](#2-containers--what-they-do)
3. [Flow 1 — SSO Login (End to End)](#3-flow-1--sso-login-end-to-end)
4. [Flow 2 — Authorization Check](#4-flow-2--authorization-check)
5. [Flow 3 — Token Refresh](#5-flow-3--token-refresh)
6. [Flow 4 — Management API (Create Org, Role, Permissions, User)](#6-flow-4--management-api)
7. [Flow 5 — CDC Pipeline (Permission Change Propagation)](#7-flow-5--cdc-pipeline)
8. [Code Map — Where Everything Lives](#8-code-map--where-everything-lives)
9. [Database — Schema, Tables, and How to Inspect](#9-database--schema-tables-and-how-to-inspect)
10. [OPA — Policy and Data Store](#10-opa--policy-and-data-store)
11. [Redis — Session State](#11-redis--session-state)
12. [Kafka & Debezium — CDC Events](#12-kafka--debezium--cdc-events)
13. [Keycloak — Identity Provider](#13-keycloak--identity-provider)
14. [JWT Token Structure](#14-jwt-token-structure)
15. [Management API — Complete Reference](#15-management-api--complete-reference)
16. [Configuration Reference](#16-configuration-reference)
17. [Debugging Checklist](#17-debugging-checklist)

---

## 1. How to Start the System

```bash
cd v2/
docker-compose up -d
```

Wait ~90 seconds for all services to be healthy (Keycloak takes the longest).

```bash
# Check all services are up
docker-compose ps

# Verify auth server
curl http://localhost:8000/health

# Verify OPA
curl http://localhost:8181/health

# Open Swagger UI
# http://localhost:8000/docs

# Open Keycloak admin console
# http://localhost:8080  (admin / admin)
```

### Port Map

| Port | Service | What to access |
|------|---------|---------------|
| 8000 | Auth Server | API endpoints, Swagger docs at `/docs` |
| 8080 | Keycloak | Admin console, realm config |
| 8181 | OPA | Policy engine API, data inspection |
| 5432 | PostgreSQL | RBAC database (`authz` schema) |
| 6379 | Redis | Sessions, token metadata |
| 9092 | Kafka (internal) | CDC event streaming |
| 29092 | Kafka (host) | For local Kafka tools |
| 8083 | Debezium | CDC connector REST API |
| 2181 | Zookeeper | Kafka coordination |

---

## 2. Containers & What They Do

There are 11 containers. Here's what each does and when you'd look at it:

### `authz-v2-auth-server` — The Main API

**What:** FastAPI application serving all auth, authorization, and management endpoints.
**When to look:** Any API behaviour issue, JWT problems, login failures.
**Logs:** `docker logs authz-v2-auth-server -f`
**Code:** `v2/auth-server/app/`

### `authz-v2-postgres` — The Database

**What:** PostgreSQL 15 with the `authz` schema. Stores all RBAC data (orgs, roles, permissions, users) and audit logs.
**When to look:** Data integrity issues, permission mismatches, checking what's actually in the DB.
**Connect:**
```bash
docker exec -it authz-v2-postgres psql -U authz -d authz
# Then: SET search_path TO authz;
```

### `authz-v2-opa` — Policy Engine

**What:** Open Policy Agent running in server mode. Receives data from sync-worker, evaluates Rego policies.
**When to look:** Authorization decisions are wrong, permissions not reflecting changes.
**Inspect:**
```bash
# See all RBAC data
curl http://localhost:8181/v1/data/rbac | jq

# See all user mappings
curl http://localhost:8181/v1/data/users | jq

# Test a policy query
curl -X POST http://localhost:8181/v1/data/authz/allow \
  -d '{"input":{"user":"testuser@acme.com","platform":"mlops","resource":"projects","action":"read"}}' | jq
```

### `authz-v2-redis` — Session Store

**What:** Redis 7 storing login state, refresh token metadata, and revocation list.
**When to look:** Login state issues (CSRF failures), token refresh problems.
**Inspect:**
```bash
docker exec -it authz-v2-redis redis-cli
> KEYS *
> GET login_state:<state-uuid>
> GET refresh_token:<jti>
```

### `authz-v2-sync-worker` — CDC Sync

**What:** Python process that consumes Kafka CDC events and pushes updated RBAC bundles to OPA.
**When to look:** Permissions changed in DB but not reflecting in auth decisions.
**Logs:** `docker logs authz-v2-sync-worker -f`
**Code:** `v2/sync-worker/sync_worker.py`

### `authz-v2-kafka` — Event Streaming

**What:** Kafka broker carrying CDC events from Debezium.
**When to look:** Sync worker not receiving changes.
**Inspect:**
```bash
# List topics
docker exec authz-v2-kafka kafka-topics --bootstrap-server localhost:9092 --list

# Read messages from a topic
docker exec authz-v2-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic authz.authz.mlops_users --from-beginning --max-messages 5
```

### `authz-v2-debezium` — Change Data Capture

**What:** Debezium Connect capturing PostgreSQL WAL changes and publishing to Kafka.
**When to look:** Changes in DB not appearing in Kafka topics.
**Inspect:**
```bash
# Check connector status
curl http://localhost:8083/connectors/authz-connector/status | jq
```

### `authz-v2-keycloak` — Identity Provider

**What:** Keycloak 24 acting as the OIDC identity provider / broker.
**When to look:** Login redirects failing, token exchange errors.
**Access:** http://localhost:8080 (admin / admin)
**Config:** `v2/keycloak-config/realm-export.json`

### `authz-v2-zookeeper` — Kafka Coordination

**What:** Zookeeper managing Kafka cluster state. You almost never need to touch this.

### `authz-v2-connector-init` — One-shot Setup

**What:** Runs once on startup to register the Debezium connector with PostgreSQL. Exits after completion.
**Script:** `v2/scripts/setup.sh`

### `authz-v2-init-render` — SQL Template Rendering

**What:** Runs once on startup to render `init.sql.tpl` with platform definitions from `platforms.yaml`. Exits after completion.
**Script:** `v2/scripts/render_init.sh`

---

## 3. Flow 1 — SSO Login (End to End)

This is the most complex flow. Here's every step, which code runs, and which container to check.

### Step 1: Frontend calls POST /auth/login

```
Frontend  --->  POST http://localhost:8000/api/v1/auth/login
                Body: {"platform": "mlops", "org_name": "acme"}
```

**Container:** `auth-server`
**Code path:**
1. `app/routers/auth.py` — `login()` endpoint (line 44)
2. Validates `platform` is in `settings.PLATFORMS` list (`app/core/config.py` line 62)
3. Gets SSO config → `app/services/sso_service.py` — `get_sso_config_for_org()` (line 21)
4. Generates authorization URL → `sso_service.py` — `create_authorization_url()` (line 42)
   - Creates `state` (UUID for CSRF protection)
   - Creates `nonce` (UUID for replay protection)
   - Builds Keycloak authorize URL with `client_id`, `redirect_uri`, `state`, `nonce`
5. Stores state in Redis → `app/services/session_service.py` — `store_login_state()` (line 57)
   - Key: `login_state:{state_uuid}`
   - Value: `{platform, org_name, nonce}`
   - TTL: 600 seconds (10 minutes)

**What to check if this fails:**
- `docker logs authz-v2-auth-server` — look for error messages
- Redis: `docker exec authz-v2-redis redis-cli KEYS "login_state:*"` — verify state was stored
- Config: verify `OKTA_DOMAIN`, `OKTA_CLIENT_ID`, `REDIRECT_URI` environment variables

**Response:**
```json
{"login_url": "http://localhost:8080/realms/authz/protocol/openid-connect/auth?client_id=authz-client&..."}
```

### Step 2: User authenticates at Keycloak

The frontend redirects the user's browser to the `login_url`. The user sees the Keycloak login page and enters credentials.

**Container:** `keycloak`
**What to check:** http://localhost:8080 → Admin Console → Realm `authz` → Sessions

**Test users:**
- `testuser@acme.com` / `testpassword123`
- `admin@acme.com` / `adminpassword123`

### Step 3: Keycloak redirects back with auth code

After successful authentication, Keycloak redirects the browser to:
```
http://localhost:8000/api/v1/auth/callback?code=AUTH_CODE&state=STATE_UUID
```

### Step 4: Auth Server processes callback

**Container:** `auth-server`
**Code path:**
1. `app/routers/auth.py` — `callback()` endpoint (line 107)
2. Retrieves login state from Redis → `session_service.py` — `get_login_state()` (line 97)
   - Validates the `state` parameter matches (CSRF protection)
   - Gets back `platform`, `org_name`, `nonce`
3. Deletes login state from Redis → `session_service.py` — `delete_login_state()` (line 120)
4. Exchanges auth code for tokens → `sso_service.py` — `exchange_code_for_tokens()` (line 82)
   - POSTs to Keycloak token endpoint (server-to-server via `OKTA_ISSUER_INTERNAL`)
   - Sends: `code`, `redirect_uri`, `client_id`, `client_secret`
   - Gets back: `access_token`, `id_token`, `refresh_token` from Keycloak
5. Verifies ID token → `sso_service.py` — `verify_id_token()` (line 131)
   - Fetches JWKS from Keycloak
   - Validates RS256 signature, issuer, audience
   - Extracts `email` from claims
6. Checks user exists → `app/services/opa_service.py` — `check_user_exists()` (line 58)
   - Queries OPA: `POST /v1/data/authz/user_exists` with `{"input": {"user": email}}`
   - OPA checks: does `data.users.user_roles[email]` exist?
7. Gets user context → `opa_service.py` — `get_user_context()` (line 71)
   - Returns: `{user_id, role, organization, is_org_admin}`
8. Gets permissions → `opa_service.py` — `get_user_permissions()` (line 90)
   - Returns: `{projects: {read: true, write: false, ...}, ...}`
9. Gets role metadata → `opa_service.py` — `get_role_metadata()` (line 108)
   - Returns: `{global_access: true/false, bu_access: true/false}`
10. Creates access token → `app/services/token_service.py` — `create_access_token()` (line 29)
    - Signs JWT with HS256 using `SECRET_KEY`
    - Embeds: email, userID, organization, platform, permissions, org_admin, licence
    - Expiry: 60 minutes
11. Creates refresh token → `token_service.py` — `create_refresh_token()` (line 78)
    - Signs JWT with unique `jti` (token ID)
    - Expiry: 30 days
    - Stores metadata in Redis → `session_service.py` — `store_refresh_token()` (line 143)

**What to check if this fails:**
- Redis: verify `login_state:*` key existed when callback arrived
- Keycloak: check token endpoint is reachable from auth-server container
- OPA: `curl http://localhost:8181/v1/data/users` — does the user exist?
- Logs: `docker logs authz-v2-auth-server` — look for token exchange errors

**Response:**
```json
{
  "success": true,
  "email": "testuser@acme.com",
  "organization": "acme",
  "user_id": "uuid-123",
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "message": "Successfully logged in via SSO"
}
```

---

## 4. Flow 2 — Authorization Check

Once logged in, the frontend includes the access token in every API request.

```
Frontend  --->  POST http://localhost:8000/api/v1/authorize
                Header: Authorization: Bearer <access_token>
                Body: {"resource": "projects", "action": "write"}
```

**Container:** `auth-server`
**Code path:**
1. FastAPI extracts Bearer token → `app/core/security.py` — `HTTPBearer` (line 15)
2. `get_current_user()` dependency (line 93) decodes and validates JWT
   - `decode_token()` (line 40) — verifies HS256 signature with `SECRET_KEY`
   - `validate_token_expiry()` (line 66) — checks `exp` claim
   - Extracts: email, userID, organization, platform, is_org_admin, permissions
   - Returns `TokenData` object
3. `app/routers/authorize.py` — `authorize()` endpoint (line 24)
4. Queries OPA → `opa_service.py` — `get_authorization_response()` (line 152)
   - `POST http://opa:8181/v1/data/authz/authorization_response`
   - Input: `{user, platform, resource, action}`
5. OPA evaluates `policy.rego` — `authorization_response` rule (line 99)
   - Looks up: `data.users.user_roles[email]` → gets role
   - Looks up: `data.users.user_tenant[email]` → gets org/tenant
   - Checks: `data.rbac[platform][tenant][role][resource][action]` → true/false

**Container to check:** `opa`
```bash
# Manually test the same query OPA receives
curl -X POST http://localhost:8181/v1/data/authz/authorization_response \
  -d '{"input":{"user":"testuser@acme.com","platform":"mlops","resource":"projects","action":"write"}}' | jq
```

**Response:**
```json
{
  "allowed": true,
  "user_id": "uuid-123",
  "organization": "acme",
  "role": "viewer",
  "is_org_admin": 0
}
```

### Batch Authorization

For UIs that need to check multiple permissions at once:

```
POST /api/v1/authorize/batch
Body: [
  {"resource": "projects", "action": "read"},
  {"resource": "projects", "action": "write"},
  {"resource": "pipelines", "action": "delete"}
]
```

**Code:** `authorize.py` — `authorize_batch()` (line 83). Makes sequential OPA calls per item.

### Get Current User

```
GET /api/v1/authorize/me
Header: Authorization: Bearer <access_token>
```

**Code:** `authorize.py` — `get_me()` (line 62). Returns decoded JWT claims directly — no OPA call.

---

## 5. Flow 3 — Token Refresh

When the access token expires (after 60 min), the frontend uses the refresh token to get a new one.

```
Frontend  --->  POST http://localhost:8000/api/v1/auth/refresh
                Body: {"refresh_token": "eyJ..."}
```

**Container:** `auth-server`
**Code path:**
1. `app/routers/auth.py` — `refresh()` endpoint (line 259)
2. Validates refresh token → `token_service.py` — `validate_refresh_token()` (line 138)
   - Decodes JWT, checks `type == "refresh"`
3. Checks not revoked → `token_service.py` — `is_refresh_token_valid()` (line 186)
   - Queries Redis: `revoked_token:{jti}` and `refresh_token:{jti}`
4. Queries OPA for **latest** permissions (not from old token)
   - `opa_service.get_user_context()` → fresh role/org
   - `opa_service.get_user_permissions()` → fresh permissions
   - `opa_service.get_role_metadata()` → fresh access flags
5. Creates new access token with updated permissions
6. Returns new access token (same refresh token stays valid)

**Key insight:** This is where permission changes take effect for already-logged-in users. Even if a role's permissions were changed in the DB and synced to OPA, the user's existing access token still has the old permissions embedded. Only on refresh do they get the new ones.

---

## 6. Flow 4 — Management API

These endpoints let org admins manage organizations, roles, permissions, and users via REST instead of direct SQL.

### Prerequisites

The caller must have a valid JWT with `is_org_admin: 1` (set via the `is_org_admin` flag in the database user record).

All management endpoints use the `require_org_admin` dependency:
- **Code:** `app/core/security.py` — `require_org_admin()` (line 168)
- First validates JWT via `get_current_user()`
- Then checks `is_org_admin == 1`, returns 403 if not

The `platform` is automatically taken from the JWT — users can only manage the platform they're authenticated for.

### Example: Full Setup Flow via Management API

**Step 1 — Create an organization:**

```bash
curl -X POST http://localhost:8000/api/v1/manage/orgs \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "newcorp"}'
```

**Code path:**
1. `app/routers/manage.py` — `create_org()` (line 56)
2. `app/services/manage_service.py` — `create_org()` (line 85)
3. Resolves platform prefix → `_get_prefix()` (line 23) — queries `platforms` table
4. `INSERT INTO {prefix}_orgs (name) VALUES ($1) RETURNING id, name`
5. Writes audit → `_audit()` (line 34) — inserts into `audit_log`
6. Both in same transaction

**Container to verify:** `postgres`
```sql
SET search_path TO authz;
SELECT * FROM mlops_orgs WHERE name = 'newcorp';
SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 5;
```

**Step 2 — Create a role in the org:**

```bash
curl -X POST http://localhost:8000/api/v1/manage/orgs/<org_id>/roles \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "editor", "global_access": false, "bu_access": true}'
```

**Code path:**
1. `manage.py` — `create_role()` (line 162)
2. `manage_service.py` — `create_role()` (line 217)
3. Verifies org exists
4. `INSERT INTO {prefix}_roles (org_id, name, global_access, bu_access) ...`
5. Writes audit

**Step 3 — Grant permissions to the role:**

```bash
curl -X PUT http://localhost:8000/api/v1/manage/orgs/<org_id>/roles/<role_id>/permissions \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "permissions": [
      {"resource": "projects", "can_read": true, "can_write": true, "can_delete": false},
      {"resource": "pipelines", "can_read": true, "can_write": false, "can_delete": false}
    ]
  }'
```

**Code path:**
1. `manage.py` — `set_permissions()` (line 291)
2. `manage_service.py` — `set_permissions()` (line 386)
3. Verifies role exists in org
4. For each permission: `INSERT INTO {prefix}_perms ... ON CONFLICT DO UPDATE`
5. Writes audit with full permissions payload

**Step 4 — Add a user to the org:**

```bash
curl -X POST http://localhost:8000/api/v1/manage/orgs/<org_id>/users \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "jane@newcorp.com",
    "role_name": "editor",
    "user_uid": "idp-uid-12345",
    "is_org_admin": false
  }'
```

**Code path:**
1. `manage.py` — `add_user()` (line 354)
2. `manage_service.py` — `add_user()` (line 543)
3. Verifies org exists
4. Looks up role by name within the org
5. `INSERT INTO {prefix}_users (email, org_id, role_id, user_uid, is_org_admin) ...`
6. Writes audit

### What Happens After a Management Change

All 4 steps above wrote to PostgreSQL. Here's what happens next **automatically**:

1. PostgreSQL WAL records the INSERT/UPDATE
2. Debezium reads the WAL → publishes CDC event to Kafka topic (e.g., `authz.authz.mlops_orgs`)
3. Sync Worker consumes the Kafka message → debounces for 2 seconds
4. Sync Worker calls `generate_opa_bundle('mlops')` on PostgreSQL
5. Sync Worker PUTs the bundle to OPA at `/v1/data/rbac` and `/v1/data/users`
6. OPA now has the new data — next authorization check reflects the changes

**Total latency:** ~2-5 seconds from API call to OPA having the data.

### Updating and Deleting

**Change a user's role:**
```bash
curl -X PUT http://localhost:8000/api/v1/manage/orgs/<org_id>/users/<user_id> \
  -H "Authorization: Bearer <admin_token>" \
  -d '{"role_name": "admin"}'
```

**Code:** `manage_service.py` — `update_user()` (line 599). Looks up new role by name, updates `role_id`.

**Revoke a permission:**
```bash
curl -X DELETE http://localhost:8000/api/v1/manage/orgs/<org_id>/roles/<role_id>/permissions/pipelines \
  -H "Authorization: Bearer <admin_token>"
```

**Code:** `manage_service.py` — `delete_permission()` (line 453). Deletes the row from `{prefix}_perms`.

**Delete a role (safe):**
```bash
curl -X DELETE http://localhost:8000/api/v1/manage/orgs/<org_id>/roles/<role_id> \
  -H "Authorization: Bearer <admin_token>"
```

**Code:** `manage_service.py` — `delete_role()` (line 309). Returns **409 Conflict** if the role still has users assigned — you must reassign or remove them first.

**Delete an org (safe):**
Same pattern — returns 409 if the org still has roles. You must delete all roles first.

### Audit Log

Every management action is recorded. Query the log:

```bash
curl "http://localhost:8000/api/v1/manage/audit?org_name=newcorp&limit=20" \
  -H "Authorization: Bearer <admin_token>"
```

**Code:** `manage_service.py` — `get_audit_log()` (line 710)

**Or inspect directly in the database:**
```sql
SELECT timestamp, actor_email, action, target_type, details
FROM authz.audit_log
ORDER BY timestamp DESC LIMIT 20;
```

---

## 7. Flow 5 — CDC Pipeline

This is how database changes become authorization decisions.

### The Chain

```
PostgreSQL (WAL) → Debezium → Kafka → Sync Worker → OPA
```

### Step-by-step

**1. Something changes in PostgreSQL**

Any INSERT, UPDATE, or DELETE on `{platform}_orgs`, `{platform}_roles`, `{platform}_perms`, or `{platform}_users` tables generates a WAL (Write-Ahead Log) entry.

PostgreSQL is configured with `wal_level=logical` (see `docker-compose.yaml` line 49) to enable CDC.

**2. Debezium captures the change**

Debezium has a connector registered against PostgreSQL (set up by `connector-init` container via `scripts/setup.sh`). It reads the WAL and publishes change events to Kafka topics.

**Topic naming:** `authz.authz.{platform}_{table}`
Examples:
- `authz.authz.mlops_orgs`
- `authz.authz.mlops_roles`
- `authz.authz.mlops_perms`
- `authz.authz.mlops_users`

**Container to check:**
```bash
# Connector health
curl http://localhost:8083/connectors/authz-connector/status | jq

# See CDC messages
docker exec authz-v2-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic authz.authz.mlops_users --from-beginning --max-messages 1
```

**3. Sync Worker consumes messages**

**Code:** `v2/sync-worker/sync_worker.py`

- `watch_changes()` (line 277): Main loop
  - Creates `KafkaConsumer` subscribed to all `authz.authz.*` topics
  - On receiving messages, extracts affected platform from topic name
  - Debounces: waits 2 seconds after last message before syncing (line 183-198)
  - Calls `fetch_all_bundles()` (line 71) — queries PostgreSQL for each affected platform
  - `fetch_bundle()` (line 58) calls `SELECT generate_opa_bundle('mlops')` SQL function
  - Calls `push_data_to_opa()` (line 112) — PUTs data to OPA

**4. OPA has updated data**

Sync Worker PUTs to three OPA endpoints:
- `PUT /v1/data/rbac` — permission structure
- `PUT /v1/data/users` — user-to-role mappings
- `PUT /v1/data/platforms` — list of active platforms

Now the next call to `POST /v1/data/authz/allow` uses the new data.

### Policy Hot-Reload

The sync worker also watches the `policy.rego` file for changes:

**Code:** `sync_worker.py` — `PolicyFileHandler` class (line 178), `start_policy_watcher()` (line 201)

- Uses `watchdog` to monitor `/policy/policy.rego`
- On file change: debounces 2 seconds, then calls `push_policy_to_opa()` (line 145)
- PUTs to `OPA /v1/policies/authz`

This means you can edit `v2/opa-policy/policy.rego` while the system is running and OPA will pick it up without restart (the file is mounted as a volume).

---

## 8. Code Map — Where Everything Lives

```
v2/
├── auth-server/
│   ├── Dockerfile                            # Python 3.11 slim image
│   ├── requirements.txt                      # Dependencies (fastapi, asyncpg, etc.)
│   └── app/
│       ├── main.py                           # FastAPI app setup, lifespan, CORS, routers
│       ├── __init__.py
│       │
│       ├── core/
│       │   ├── config.py                     # All settings from environment variables
│       │   └── security.py                   # JWT validation, get_current_user, require_org_admin
│       │
│       ├── routers/
│       │   ├── __init__.py                   # Exports all routers
│       │   ├── auth.py                       # /api/v1/auth/*  — login, callback, refresh, logout
│       │   ├── authorize.py                  # /api/v1/authorize — permission checks
│       │   └── manage.py                     # /api/v1/manage/* — CRUD for orgs/roles/perms/users
│       │
│       ├── services/
│       │   ├── __init__.py                   # Exports all services
│       │   ├── opa_service.py                # HTTP client for OPA queries (read-only)
│       │   ├── sso_service.py                # OAuth/OIDC flow helpers (Keycloak/Okta)
│       │   ├── session_service.py            # Redis session/token management
│       │   ├── token_service.py              # JWT creation, validation, revocation
│       │   └── manage_service.py             # Database CRUD for management API
│       │
│       ├── models/
│       │   ├── schemas.py                    # Pydantic models for auth & authorize APIs
│       │   └── manage_schemas.py             # Pydantic models for management API
│       │
│       └── db/
│           ├── __init__.py
│           └── pool.py                       # asyncpg connection pool (init/close/get)
│
├── sync-worker/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── sync_worker.py                        # CDC consumer: Kafka → PostgreSQL → OPA
│
├── db/
│   ├── platforms.yaml                        # Platform definitions (mlops, analytics, vision, DC)
│   └── init.sql.tpl                          # SQL template: schema, functions, audit table
│
├── opa-policy/
│   └── policy.rego                           # Rego authorization rules
│
├── keycloak-config/
│   └── realm-export.json                     # Keycloak realm with IdP connections
│
├── scripts/
│   ├── render_init.sh                        # Renders init.sql.tpl → generated/init.sql
│   └── setup.sh                              # Registers Debezium connector
│
├── docker-compose.yaml                       # All 11 services
├── e2e_test.py                               # End-to-end tests
├── e2e_browser_test.py                       # Browser-based E2E tests
└── e2e_interactive_test.py                   # Interactive testing
```

### Which file to look at for what

| I want to... | Look at |
|---|---|
| Understand how login works | `routers/auth.py` → `login()` and `callback()` |
| Debug JWT creation | `services/token_service.py` → `create_access_token()` |
| See what's in the JWT | `services/token_service.py` line 42-67 (claims) |
| Debug OAuth code exchange | `services/sso_service.py` → `exchange_code_for_tokens()` |
| Understand permission checks | `routers/authorize.py` → `authorize()`, then `opa_service.py` |
| See how OPA evaluates policy | `opa-policy/policy.rego` |
| Debug why permissions are stale | `sync-worker/sync_worker.py` → `watch_changes()` |
| Understand the DB schema | `db/init.sql.tpl` |
| Check how management CRUD works | `routers/manage.py` → `services/manage_service.py` |
| See what gets audited | `services/manage_service.py` → `_audit()` function |
| Change environment settings | `core/config.py` → `Settings` class |
| Understand Redis key structure | `services/session_service.py` — key generators (line 41-51) |

---

## 9. Database — Schema, Tables, and How to Inspect

### Connecting

```bash
docker exec -it authz-v2-postgres psql -U authz -d authz
```

Then always:
```sql
SET search_path TO authz;
```

### Schema Layout

**Global tables:**

| Table | Purpose |
|-------|---------|
| `platforms` | Registry of platforms (mlops, analytics, vision, DC) |
| `audit_log` | Audit trail of all management actions |

**Per-platform tables** (e.g., for `mlops`):

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `mlops_orgs` | Organizations | `id`, `name` |
| `mlops_roles` | Roles per org | `id`, `org_id`, `name`, `global_access`, `bu_access` |
| `mlops_perms` | Permissions per role | `role_id`, `resource`, `can_read`, `can_write`, `can_delete` |
| `mlops_users` | Users per org+role | `id`, `email`, `org_id`, `role_id`, `user_uid`, `is_org_admin` |

Same tables exist for `analytics_*`, `vision_*`, `dc_*`.

### Useful Queries

```sql
-- See all platforms
SELECT * FROM platforms;

-- See all orgs for mlops
SELECT * FROM mlops_orgs;

-- See all roles with their org
SELECT r.*, o.name AS org_name FROM mlops_roles r JOIN mlops_orgs o ON o.id = r.org_id;

-- See all permissions for a role
SELECT r.name AS role, p.resource, p.can_read, p.can_write, p.can_delete
FROM mlops_perms p
JOIN mlops_roles r ON r.id = p.role_id;

-- See all users with role and org
SELECT u.email, r.name AS role, o.name AS org, u.is_org_admin
FROM mlops_users u
JOIN mlops_roles r ON r.id = u.role_id
JOIN mlops_orgs o ON o.id = u.org_id;

-- Generate the bundle that gets pushed to OPA (what sync-worker calls)
SELECT generate_opa_bundle('mlops');

-- View recent audit log
SELECT timestamp, actor_email, action, target_type, details
FROM audit_log ORDER BY timestamp DESC LIMIT 20;
```

### SQL Helper Functions (for manual use)

These exist in the database for direct SQL operations (the management API uses `manage_service.py` instead):

```sql
SELECT add_org('mlops', 'newcorp');
SELECT add_role('mlops', 'newcorp', 'viewer', false, true);
SELECT set_perm('mlops', 'newcorp', 'viewer', 'projects', true, false, false);
SELECT add_user('mlops', 'newcorp', 'bob@newcorp.com', 'viewer', 'uid-bob', false);
```

---

## 10. OPA — Policy and Data Store

### How to Inspect OPA

```bash
# All RBAC data (permission structure)
curl http://localhost:8181/v1/data/rbac | jq

# All user mappings
curl http://localhost:8181/v1/data/users | jq

# List of platforms
curl http://localhost:8181/v1/data/platforms | jq

# Current policy
curl http://localhost:8181/v1/policies/authz
```

### Data Structure in OPA

After sync, OPA holds this data:

```json
{
  "rbac": {
    "mlops": {
      "acme": {
        "admin": {
          "projects": {"read": true, "write": true, "delete": true},
          "pipelines": {"read": true, "write": true, "delete": false},
          "global_access": true,
          "bu_access": false
        },
        "viewer": {
          "projects": {"read": true, "write": false, "delete": false},
          "global_access": false,
          "bu_access": true
        }
      }
    }
  },
  "users": {
    "user_roles": {"testuser@acme.com": "viewer", "admin@acme.com": "admin"},
    "user_tenant": {"testuser@acme.com": "acme", "admin@acme.com": "acme"},
    "user_ids": {"testuser@acme.com": "uid-1", "admin@acme.com": "uid-2"},
    "org_admin_flag": {"testuser@acme.com": 0, "admin@acme.com": 1}
  },
  "platforms": ["mlops", "analytics", "vision", "DC"]
}
```

### Testing a Policy Decision Manually

```bash
# Does testuser@acme.com have write access to projects on mlops?
curl -X POST http://localhost:8181/v1/data/authz/allow \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "user": "testuser@acme.com",
      "platform": "mlops",
      "resource": "projects",
      "action": "write"
    }
  }' | jq
```

### Policy Rules (policy.rego)

| Rule | What it does | Input needed |
|------|-------------|-------------|
| `allow` | Main permission check | user, platform, resource, action |
| `user_exists` | Does user exist? | user |
| `user_context` | Get user info (for JWT) | user, platform |
| `user_permissions` | Get all permissions | user, platform |
| `role_metadata` | Get global/bu access flags | user, platform |
| `authorization_response` | Full decision with context | user, platform, resource, action |

---

## 11. Redis — Session State

### Connecting

```bash
docker exec -it authz-v2-redis redis-cli
```

### Key Patterns

| Pattern | Purpose | TTL | Set by |
|---------|---------|-----|--------|
| `login_state:{uuid}` | OAuth state (CSRF) | 10 min | `session_service.store_login_state()` |
| `refresh_token:{jti}` | Refresh token metadata | 30 days | `session_service.store_refresh_token()` |
| `revoked_token:{jti}` | Revocation blacklist | Until token expiry | `session_service.revoke_token()` |

### Inspecting

```bash
# List all keys
KEYS *

# See a login state
GET login_state:some-uuid

# See a refresh token
GET refresh_token:some-jti

# Check if token is revoked
EXISTS revoked_token:some-jti
```

---

## 12. Kafka & Debezium — CDC Events

### Topics

Debezium creates one topic per table it monitors:

```
authz.authz.mlops_orgs
authz.authz.mlops_roles
authz.authz.mlops_perms
authz.authz.mlops_users
authz.authz.analytics_orgs
authz.authz.analytics_roles
... (same for each platform)
```

### Inspecting

```bash
# List all topics
docker exec authz-v2-kafka kafka-topics --bootstrap-server localhost:9092 --list

# Read CDC messages from a topic
docker exec authz-v2-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic authz.authz.mlops_users \
  --from-beginning --max-messages 3

# Check Debezium connector status
curl http://localhost:8083/connectors/authz-connector/status | jq
```

### CDC Message Format (Debezium)

Each message contains a `before` and `after` snapshot:

```json
{
  "before": null,
  "after": {
    "id": "uuid-123",
    "email": "jane@acme.com",
    "org_id": "uuid-org",
    "role_id": "uuid-role",
    "user_uid": "idp-uid",
    "is_org_admin": false
  },
  "op": "c",
  "ts_ms": 1710000000000
}
```

`op` values: `c` = create, `u` = update, `d` = delete, `r` = read (snapshot)

---

## 13. Keycloak — Identity Provider

### Admin Console

**URL:** http://localhost:8080
**Credentials:** admin / admin

### Realm: `authz`

The `authz` realm is pre-configured with:

- **Client:** `authz-client` (OAuth client used by the auth server)
- **Redirect URI:** `http://localhost:8000/api/v1/auth/callback`

### Test Users

| Email | Password | Intended Role |
|-------|----------|------|
| `testuser@acme.com` | `testpassword123` | Viewer |
| `admin@acme.com` | `adminpassword123` | Admin |
| `test.user@gmail.com` | `test.user` | Test |

### Federated IdP Connections

Configured in `realm-export.json` (need real credentials to work):

| Provider | Type |
|----------|------|
| Okta | OIDC |
| Azure AD | SAML/OIDC |
| Auth0 | OIDC |

### Where to look

- **Users:** Admin Console → Realm `authz` → Users
- **Sessions:** Admin Console → Realm `authz` → Sessions
- **Client config:** Admin Console → Realm `authz` → Clients → `authz-client`
- **IdP connections:** Admin Console → Realm `authz` → Identity Providers

---

## 14. JWT Token Structure

### Access Token Claims

Created by `token_service.py` → `create_access_token()` (line 29):

```json
{
  "email": "testuser@acme.com",
  "userID": "uuid-123",
  "organization": "acme",
  "platform": "mlops",
  "org_admin": 0,
  "permissions": {
    "projects": {"read": true, "write": false, "delete": false},
    "pipelines": {"read": true, "write": false, "delete": false},
    "global_access": false,
    "bu_access": true
  },
  "licence": { "...hardcoded licence blob..." },
  "iat": 1710000000,
  "exp": 1710003600,
  "type": "access"
}
```

**Algorithm:** HS256 signed with `SECRET_KEY`
**Expiry:** 60 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)

### Refresh Token Claims

Created by `token_service.py` → `create_refresh_token()` (line 78):

```json
{
  "email": "testuser@acme.com",
  "platform": "mlops",
  "jti": "unique-token-id",
  "iat": 1710000000,
  "exp": 1712592000,
  "type": "refresh"
}
```

**Expiry:** 30 days (configurable via `REFRESH_TOKEN_EXPIRE_DAYS`)
**Tracked in Redis:** `refresh_token:{jti}` key with metadata

### Decoding a Token (for debugging)

```bash
# Paste the JWT into jwt.io, or:
echo "eyJ..." | cut -d. -f2 | base64 -d 2>/dev/null | jq
```

---

## 15. Management API — Complete Reference

All endpoints are under `/api/v1/manage` and require `Authorization: Bearer <token>` with `is_org_admin: 1`.

### Organizations

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| GET | `/manage/orgs` | — | `{orgs: [...], total}` | Lists orgs for caller's platform |
| POST | `/manage/orgs` | `{name}` | `{id, name}` | 201 Created, 409 if duplicate |
| GET | `/manage/orgs/{org_id}` | — | `{id, name}` | 404 if not found |
| PUT | `/manage/orgs/{org_id}` | `{name}` | `{id, name}` | 409 if duplicate name |
| DELETE | `/manage/orgs/{org_id}` | — | 204 No Content | 409 if org has roles |

### Roles

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| GET | `/manage/orgs/{org_id}/roles` | — | `{roles: [...], total}` | |
| POST | `/manage/orgs/{org_id}/roles` | `{name, global_access, bu_access}` | `{id, name, ...}` | 201, 409 if duplicate |
| GET | `/manage/orgs/{org_id}/roles/{role_id}` | — | Role + permissions[] | |
| PUT | `/manage/orgs/{org_id}/roles/{role_id}` | `{name?, global_access?, bu_access?}` | `{id, name, ...}` | Partial update |
| DELETE | `/manage/orgs/{org_id}/roles/{role_id}` | — | 204 | 409 if role has users |

### Permissions

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| GET | `.../roles/{role_id}/permissions` | — | `{role_name, permissions[], total}` | |
| PUT | `.../roles/{role_id}/permissions` | `{permissions: [{resource, can_read, can_write, can_delete}]}` | Same | Bulk upsert |
| DELETE | `.../roles/{role_id}/permissions/{resource}` | — | 204 | Revokes all perms on resource |

### Users

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| GET | `/manage/orgs/{org_id}/users` | — | `{users: [...], total}` | |
| POST | `/manage/orgs/{org_id}/users` | `{email, role_name, user_uid, is_org_admin}` | `{id, email, ...}` | 201, 409 if duplicate email |
| GET | `/manage/orgs/{org_id}/users/{user_id}` | — | `{id, email, role_name, ...}` | |
| PUT | `/manage/orgs/{org_id}/users/{user_id}` | `{role_name?, is_org_admin?}` | Updated user | Partial update |
| DELETE | `/manage/orgs/{org_id}/users/{user_id}` | — | 204 | |

### Audit Log

| Method | Path | Query Params | Response |
|--------|------|-------------|----------|
| GET | `/manage/audit` | `org_name`, `limit` (1-200), `offset` | `{entries: [...], total}` |

---

## 16. Configuration Reference

All settings are in `app/core/config.py` and loaded from environment variables.

| Variable | Default | Used By | Purpose |
|----------|---------|---------|---------|
| `SECRET_KEY` | **required** | token_service | JWT signing key |
| `ALGORITHM` | `HS256` | token_service, security | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | token_service | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | token_service | Refresh token lifetime |
| `DEBUG` | `false` | auth router | Enables /test-login endpoint |
| `OKTA_DOMAIN` | **required** | sso_service | IdP domain |
| `OKTA_ISSUER` | **required** | sso_service | External IdP URL (browser redirects) |
| `OKTA_ISSUER_INTERNAL` | `""` | sso_service | Internal IdP URL (server-to-server in Docker) |
| `OKTA_CLIENT_ID` | **required** | sso_service | OAuth client ID |
| `OKTA_CLIENT_SECRET` | **required** | sso_service | OAuth client secret |
| `REDIRECT_URI` | **required** | sso_service | OAuth callback URL |
| `OPA_URL` | `http://opa:8181` | opa_service | OPA endpoint |
| `REDIS_URL` | `redis://redis:6379` | session_service | Redis endpoint |
| `SESSION_TTL_SECONDS` | `600` | session_service | Login state TTL (10 min) |
| `PLATFORMS` | `["mlops","analytics","vision","DC"]` | auth router | Valid platform names |
| `POSTGRES_HOST` | `postgres` | db/pool | Database host |
| `POSTGRES_PORT` | `5432` | db/pool | Database port |
| `POSTGRES_DB` | `authz` | db/pool | Database name |
| `POSTGRES_USER` | `authz` | db/pool | Database user |
| `POSTGRES_PASSWORD` | `authz123` | db/pool | Database password |
| `POSTGRES_MIN_POOL` | `2` | db/pool | Min connection pool size |
| `POSTGRES_MAX_POOL` | `10` | db/pool | Max connection pool size |

---

## 17. Debugging Checklist

### "User can't log in"

1. Check auth-server logs: `docker logs authz-v2-auth-server -f`
2. Is Keycloak healthy? `curl http://localhost:8080/health/ready`
3. Can auth-server reach Keycloak internally? The `OKTA_ISSUER_INTERNAL` must resolve inside Docker network
4. Is Redis up? `docker exec authz-v2-redis redis-cli ping`
5. Is the login state being stored? `redis-cli KEYS "login_state:*"`

### "User logged in but gets 'not registered' error"

1. Check OPA has the user: `curl http://localhost:8181/v1/data/users/user_roles | jq`
2. Check database has the user: `SELECT * FROM mlops_users WHERE email = '...'`
3. Check sync-worker is running: `docker logs authz-v2-sync-worker -f`
4. If user was just added, wait ~5 seconds for CDC sync

### "Permissions changed but not taking effect"

1. **For new logins:** Changes should be immediate (OPA is queried during callback)
2. **For existing tokens:** Permissions are embedded in the JWT. User must call `/auth/refresh` to get a new access token with updated permissions
3. Check OPA has new data: `curl http://localhost:8181/v1/data/rbac/mlops | jq`
4. If OPA is stale, check sync-worker: `docker logs authz-v2-sync-worker -f`
5. Check Kafka topics have the CDC event: `kafka-console-consumer --topic authz.authz.mlops_perms`
6. Check Debezium connector: `curl http://localhost:8083/connectors/authz-connector/status | jq`

### "Management API returns 403"

1. Decode the JWT — check `org_admin` claim is `1`
2. The user must have `is_org_admin = true` in the database
3. Verify via SQL: `SELECT email, is_org_admin FROM mlops_users WHERE email = '...'`
4. If the user was just promoted to admin, they need to refresh their token (the old JWT still has `org_admin: 0`)

### "Management API returns 409 Conflict on delete"

1. **Deleting an org:** It still has roles. List and delete roles first.
   `GET /manage/orgs/{org_id}/roles` → delete each → then delete org
2. **Deleting a role:** It still has users. Reassign or remove users first.
   `GET /manage/orgs/{org_id}/users` → update/remove each → then delete role

### "Database changes not reaching OPA"

Check the full CDC chain in order:
1. **PostgreSQL WAL:** `SELECT * FROM pg_replication_slots;` — are slots active?
2. **Debezium:** `curl http://localhost:8083/connectors/authz-connector/status | jq` — is it RUNNING?
3. **Kafka:** Are topics being created? `kafka-topics --list`
4. **Sync Worker:** Is it consuming? `docker logs authz-v2-sync-worker -f` — look for `[SYNC]` messages
5. **OPA:** Does it have data? `curl http://localhost:8181/v1/data/rbac | jq`
