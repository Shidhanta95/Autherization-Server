# Configuration Reference

Complete reference for all configuration options.

## Environment Variables

### Auth Server Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | **Yes** | - | Secret key for JWT signing. Use a strong random string. |
| `ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `60` | Access token lifetime in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `30` | Refresh token lifetime in days |

### Okta/IdP Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OKTA_DOMAIN` | **Yes** | - | Okta domain (e.g., `dev-123456.okta.com`) |
| `OKTA_ISSUER` | **Yes** | - | Okta issuer URL (e.g., `https://dev-123456.okta.com/oauth2/default`) |
| `OKTA_CLIENT_ID` | **Yes** | - | OAuth client ID from Okta |
| `OKTA_CLIENT_SECRET` | **Yes** | - | OAuth client secret from Okta |
| `REDIRECT_URI` | **Yes** | - | Callback URL (e.g., `http://localhost:8000/api/v1/auth/callback`) |

### Service URLs

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPA_URL` | No | `http://opa:8181` | OPA service URL |
| `REDIS_URL` | No | `redis://redis:6379` | Redis connection URL |

### Session Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SESSION_TTL_SECONDS` | No | `600` | Login state TTL (10 minutes) |

### Platform Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PLATFORMS` | No | `["mlops","analytics","vision","DC"]` | Allowed platform names |

---

## Example .env File

```bash
# ============================================================
# Auth Server Configuration
# ============================================================

# REQUIRED: JWT signing key (generate with: openssl rand -hex 32)
SECRET_KEY=your-256-bit-secret-key-here-change-in-production

# Token lifetimes
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30

# ============================================================
# Okta Configuration
# ============================================================

# REQUIRED: Your Okta domain and credentials
OKTA_DOMAIN=dev-123456.okta.com
OKTA_ISSUER=https://dev-123456.okta.com/oauth2/default
OKTA_CLIENT_ID=0oa1234567890abcdef
OKTA_CLIENT_SECRET=abcdefghijklmnopqrstuvwxyz123456

# REQUIRED: Must match Okta application settings
REDIRECT_URI=http://localhost:8000/api/v1/auth/callback

# ============================================================
# Service URLs (defaults work for docker-compose)
# ============================================================

OPA_URL=http://opa:8181
REDIS_URL=redis://redis:6379
```

---

## Sync Worker Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | No | `kafka:9092` | Kafka broker address |
| `POSTGRES_HOST` | No | `postgres` | PostgreSQL host |
| `POSTGRES_DB` | No | `authz` | Database name |
| `POSTGRES_USER` | No | `authz` | Database user |
| `POSTGRES_PASSWORD` | No | `authz123` | Database password |
| `OPA_URL` | No | `http://opa:8181` | OPA service URL |
| `TOPIC_PREFIX` | No | `authz.authz` | Kafka topic prefix |
| `POLICY_FILE` | No | `/policy/policy.rego` | Path to policy file |

---

## PostgreSQL Configuration

The PostgreSQL instance requires specific settings for CDC:

```yaml
command:
  - "postgres"
  - "-c"
  - "wal_level=logical"        # Enable logical replication
  - "-c"
  - "max_replication_slots=4"  # Debezium needs slots
  - "-c"
  - "max_wal_senders=4"        # WAL streaming connections
```

---

## Platform Configuration

Platforms are defined in `db/platforms.yaml`:

```yaml
platforms:
  - name: mlops
  - name: analytics
  - name: vision
  - name: DC
```

To add a new platform:
1. Add entry to `platforms.yaml`
2. Restart the `init-render` and `postgres` services
3. Sync worker will automatically discover new tables

---

## Okta Application Setup

### 1. Create Application in Okta

1. Go to Okta Admin Console
2. Applications → Create App Integration
3. Select "OIDC - OpenID Connect"
4. Select "Web Application"

### 2. Configure Application

| Setting | Value |
|---------|-------|
| Sign-in redirect URIs | `http://localhost:8000/api/v1/auth/callback` |
| Sign-out redirect URIs | `http://localhost:8000` |
| Controlled access | Assign users/groups as needed |

### 3. Get Credentials

From the application's General tab:
- Copy **Client ID** → `OKTA_CLIENT_ID`
- Copy **Client Secret** → `OKTA_CLIENT_SECRET`

From the Okta domain:
- Your Okta URL → `OKTA_DOMAIN`
- Issuer URI (found in API → Authorization Servers) → `OKTA_ISSUER`

---

## Security Recommendations

### Production Checklist

- [ ] Use strong, unique `SECRET_KEY` (256-bit minimum)
- [ ] Store secrets in secure vault (not in files)
- [ ] Use HTTPS for all endpoints
- [ ] Configure proper CORS origins (not `*`)
- [ ] Set appropriate token lifetimes
- [ ] Enable Okta MFA for all users
- [ ] Use production-grade Redis with auth
- [ ] Enable PostgreSQL SSL connections

### Secret Key Generation

```bash
# Generate a secure secret key
openssl rand -hex 32

# Or with Python
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Docker Compose Override

For local development, create `docker-compose.override.yaml`:

```yaml
version: '3.8'

services:
  auth-server:
    environment:
      DEBUG: "true"
      SECRET_KEY: dev-secret-key-not-for-production
    volumes:
      - ./auth-server/app:/app/app  # Hot reload
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Troubleshooting Configuration

### Common Issues

**"Invalid token" errors**
- Check `SECRET_KEY` is the same across restarts
- Verify token hasn't expired

**"SSO not configured" errors**
- Verify Okta credentials are correct
- Check `REDIRECT_URI` matches Okta settings exactly

**"User not found" errors**
- User must be pre-provisioned in database
- Check OPA has synced (view `http://localhost:8181/v1/data/users`)

**OPA connection errors**
- Verify OPA is running: `curl http://localhost:8181/health`
- Check `OPA_URL` is correct

**Redis connection errors**
- Verify Redis is running: `redis-cli ping`
- Check `REDIS_URL` format
