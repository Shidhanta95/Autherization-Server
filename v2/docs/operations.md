# Operations Guide

Guide for operating and maintaining the User Management System.

## Deployment

### Initial Deployment

```bash
# 1. Clone repository
cd v2

# 2. Configure environment
cp auth-server/.env.example auth-server/.env
# Edit .env with production values

# 3. Start all services
docker-compose up -d

# 4. Verify all services are healthy
docker-compose ps

# 5. Check logs
docker-compose logs -f auth-server
```

### Service Dependencies

```
init-render → postgres → debezium → connector-init → sync-worker
                     ↘           ↘
              zookeeper → kafka
                              ↘
                               opa → auth-server
                                 ↗
                             redis
```

## Adding Users

### Via SQL (Current Method)

```sql
-- Connect to PostgreSQL
docker exec -it authz-v2-postgres psql -U authz -d authz

-- Set schema
SET search_path TO authz, public;

-- Add organization (if new)
SELECT add_org('mlops', 'newcorp');

-- Add role
SELECT add_role('mlops', 'newcorp', 'developer', false, false);

-- Set permissions for role
SELECT set_perm('mlops', 'newcorp', 'developer', 'projects', true, true, false);
SELECT set_perm('mlops', 'newcorp', 'developer', 'pipelines', true, false, false);

-- Add user
SELECT add_user('mlops', 'newcorp', 'user@newcorp.com', 'developer', 'user-uuid-here', false);
```

### Verify User in OPA

```bash
# Check if user exists in OPA
curl -s http://localhost:8181/v1/data/users/user_roles | jq

# Check user's permissions
curl -X POST http://localhost:8181/v1/data/authz/user_permissions \
  -H "Content-Type: application/json" \
  -d '{"input": {"user": "user@newcorp.com", "platform": "mlops"}}' | jq
```

## Adding a New Platform

### 1. Update platforms.yaml

```yaml
platforms:
  - name: mlops
  - name: analytics
  - name: vision
  - name: DC
  - name: newplatform  # Add new platform
```

### 2. Regenerate and Apply

```bash
# Regenerate init.sql
docker-compose run --rm init-render

# View generated SQL
cat generated/init.sql

# Restart PostgreSQL (will run init on empty DB)
# OR execute the platform creation manually:
docker exec -it authz-v2-postgres psql -U authz -d authz -c \
  "SELECT create_platform('newplatform', NULL);"
```

### 3. Verify

```bash
# Check platform was created
docker exec -it authz-v2-postgres psql -U authz -d authz -c \
  "SELECT * FROM platforms;"

# Sync worker should detect new tables
docker-compose logs sync-worker
```

## Monitoring

### Health Checks

```bash
# Auth Server
curl http://localhost:8000/health

# OPA
curl http://localhost:8181/health

# PostgreSQL
docker exec authz-v2-postgres pg_isready -U authz

# Redis
docker exec authz-v2-redis redis-cli ping

# Kafka
docker exec authz-v2-kafka kafka-broker-api-versions --bootstrap-server localhost:9092
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f auth-server
docker-compose logs -f sync-worker

# OPA decision logs
docker-compose logs -f opa | grep "decision_log"
```

### View OPA Data

```bash
# All data
curl -s http://localhost:8181/v1/data | jq

# RBAC data
curl -s http://localhost:8181/v1/data/rbac | jq

# Users data
curl -s http://localhost:8181/v1/data/users | jq

# Specific user
curl -s http://localhost:8181/v1/data/users/user_roles | jq '."user@example.com"'
```

## Troubleshooting

### Common Issues

#### "User not registered" on login

**Symptoms:** User authenticates with Okta but gets 403 error.

**Cause:** User not provisioned in authorization database.

**Fix:**
```sql
-- Add user to database
SELECT add_user('mlops', 'orgname', 'user@email.com', 'rolename', 'user-uuid', false);
```

#### Permissions not updating

**Symptoms:** User's permissions don't reflect recent changes.

**Cause:** CDC sync delay or sync worker issues.

**Fix:**
```bash
# 1. Check sync worker logs
docker-compose logs sync-worker

# 2. Manually trigger sync by restarting
docker-compose restart sync-worker

# 3. Verify OPA has latest data
curl -s http://localhost:8181/v1/data/users | jq
```

#### "Invalid state" error on callback

**Symptoms:** User redirected to login, gets "Invalid or expired state" error.

**Cause:** Login state expired (>10 min) or Redis issue.

**Fix:**
```bash
# Check Redis is working
docker exec authz-v2-redis redis-cli ping

# Check Redis data
docker exec authz-v2-redis redis-cli keys "login_state:*"

# Restart login flow
```

#### OPA returns empty permissions

**Symptoms:** User has no permissions in JWT.

**Cause:** OPA data not synced or platform mismatch.

**Fix:**
```bash
# Check OPA has RBAC data
curl -s http://localhost:8181/v1/data/rbac | jq

# Verify platform exists
curl -s http://localhost:8181/v1/data/rbac/mlops | jq

# Verify user is mapped
curl -s http://localhost:8181/v1/data/users/user_tenant | jq
```

#### Debezium connector not working

**Symptoms:** Changes to PostgreSQL not reflected in OPA.

**Fix:**
```bash
# Check connector status
curl -s http://localhost:8083/connectors/authz-connector/status | jq

# Restart connector
curl -X POST http://localhost:8083/connectors/authz-connector/restart

# Delete and recreate
curl -X DELETE http://localhost:8083/connectors/authz-connector
docker-compose restart connector-init
```

### Debug Commands

```bash
# View all running containers
docker-compose ps

# Check container resource usage
docker stats

# Enter container shell
docker exec -it authz-v2-auth-server /bin/bash

# View PostgreSQL tables
docker exec -it authz-v2-postgres psql -U authz -d authz -c "\dt authz.*"

# View Kafka topics
docker exec authz-v2-kafka kafka-topics --list --bootstrap-server localhost:9092

# View Kafka messages
docker exec authz-v2-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic authz.authz.mlops_users \
  --from-beginning
```

## Backup and Recovery

### PostgreSQL Backup

```bash
# Create backup
docker exec authz-v2-postgres pg_dump -U authz authz > backup_$(date +%Y%m%d).sql

# Restore backup
cat backup.sql | docker exec -i authz-v2-postgres psql -U authz -d authz
```

### Redis Backup

```bash
# Trigger save
docker exec authz-v2-redis redis-cli BGSAVE

# Copy RDB file
docker cp authz-v2-redis:/data/dump.rdb ./redis_backup.rdb
```

## Scaling

### Auth Server

The auth server is stateless and can be scaled horizontally:

```yaml
# docker-compose.override.yaml
services:
  auth-server:
    deploy:
      replicas: 3
```

Use a load balancer in front of multiple instances.

### OPA

OPA instances can be replicated with the same data:

```yaml
services:
  opa:
    deploy:
      replicas: 2
```

Sync worker will push data to all OPA instances (requires modification).

## Maintenance

### Rotating Secrets

1. Generate new SECRET_KEY
2. Update .env file
3. Restart auth-server
4. All existing tokens become invalid (users must re-login)

### Updating Services

```bash
# Pull latest images
docker-compose pull

# Recreate containers
docker-compose up -d --force-recreate

# Or specific service
docker-compose up -d --force-recreate auth-server
```

### Cleaning Up

```bash
# Remove stopped containers
docker-compose down

# Remove volumes (⚠️ deletes data)
docker-compose down -v

# Remove unused images
docker image prune -a
```
