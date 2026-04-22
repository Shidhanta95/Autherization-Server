#!/usr/bin/env python3
"""
E2E Test: Role CRUD API + CDC Pipeline + Token Refresh

Tests the complete lifecycle:
  Phase 0 — Bootstrap (seed org, admin role, admin user, wait for OPA sync)
  Phase 1 — CREATE role, set permissions, add user, verify CDC + token
  Phase 2 — READ role list, role detail, permissions
  Phase 3 — UPDATE role metadata + permissions, verify CDC + refreshed token
  Phase 4 — DELETE user then role, verify CDC + login blocked
  Phase 5 — Negative cases (duplicate, conflict, bad input, no admin)

Prerequisites:
    docker compose up -d   (all services healthy)

Usage:
    python e2e_role_crud_test.py
"""

import sys
import os
import re
import time
import json
import uuid
import requests
import psycopg2
from datetime import datetime, timedelta, timezone
from jose import jwt

# ============================================================
# CONFIGURATION
# ============================================================
AUTH_SERVER_URL = "http://localhost:8000"
OPA_URL = "http://localhost:8181"

POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "authz",
    "user": "authz",
    "password": "authz123",
}

SECRET_KEY = "change-this-in-production-use-a-strong-secret"
ALGORITHM = "HS256"

PLATFORM = "mlops"
ORG_NAME = "acme"
ADMIN_EMAIL = "admin@acme.com"
TEST_USER_EMAIL = "e2e-roletest@acme.com"
TEST_USER_UID = "e2e-roletest-uid"

CDC_POLL_INTERVAL = 1
CDC_POLL_MAX_WAIT = 30

# ============================================================
# OUTPUT HELPERS
# ============================================================
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

passed = 0
failed = 0
errors = []
start_time = None
_log_file = None
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _strip_ansi(text):
    return _ANSI_RE.sub("", text)


def _init_log_file():
    """Open a timestamped log file in test-results/."""
    global _log_file
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test-results")
    os.makedirs(results_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(results_dir, f"role_crud_{ts}.log")
    _log_file = open(path, "w", encoding="utf-8")
    return path


def _close_log_file():
    global _log_file
    if _log_file:
        _log_file.close()
        _log_file = None


def tee(msg="", end="\n"):
    """Print to console (with color) and log file (plain text)."""
    print(msg, end=end)
    if _log_file:
        _log_file.write(_strip_ansi(msg) + end)
        _log_file.flush()


def banner(text, char="="):
    w = 72
    tee(f"\n{BOLD}{char * w}{RESET}")
    tee(f"{BOLD}{text.center(w)}{RESET}")
    tee(f"{BOLD}{char * w}{RESET}\n")


def phase(num, title):
    tee(f"\n{BLUE}{BOLD}{'━' * 72}{RESET}")
    tee(f"{BLUE}{BOLD}  PHASE {num} — {title}{RESET}")
    tee(f"{BLUE}{BOLD}{'━' * 72}{RESET}")


def step(msg):
    tee(f"\n  {CYAN}▸{RESET} {msg}")


def ok(msg):
    global passed
    passed += 1
    tee(f"    {GREEN}✓{RESET} {msg}")


def fail(msg):
    global failed
    failed += 1
    errors.append(msg)
    tee(f"    {RED}✗{RESET} {msg}")


def info(msg):
    tee(f"    {YELLOW}→{RESET} {msg}")


def detail(k, v):
    tee(f"      {DIM}•{RESET} {k}: {CYAN}{v}{RESET}")


def json_detail(label, data):
    tee(f"      {DIM}•{RESET} {label}:")
    for line in json.dumps(data, indent=2, default=str).split("\n"):
        tee(f"        {CYAN}{line}{RESET}")


def comparison(before_label, before_data, after_label, after_data):
    tee(f"\n    {YELLOW}BEFORE ({before_label}):{RESET}")
    for line in json.dumps(before_data, indent=2, default=str).split("\n"):
        tee(f"      {RED}{line}{RESET}")
    tee(f"    {YELLOW}AFTER ({after_label}):{RESET}")
    for line in json.dumps(after_data, indent=2, default=str).split("\n"):
        tee(f"      {GREEN}{line}{RESET}")


# ============================================================
# HTTP HELPERS
# ============================================================
def api(method, path, token=None, log=True, **kwargs):
    url = f"{AUTH_SERVER_URL}{path}"
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = kwargs.get("json")

    if log:
        if body:
            tee(f"    {MAGENTA}>{RESET} {DIM}{method.upper()} {path}{RESET}  {DIM}body={json.dumps(body, default=str)[:120]}{RESET}")
        else:
            tee(f"    {MAGENTA}>{RESET} {DIM}{method.upper()} {path}{RESET}")

    resp = getattr(requests, method)(url, headers=headers, timeout=15, **kwargs)

    if log:
        status_color = GREEN if resp.status_code < 400 else RED
        try:
            resp_body = resp.json()
            truncated = json.dumps(resp_body, default=str)
            if len(truncated) > 200:
                truncated = truncated[:200] + "..."
            tee(f"    {MAGENTA}<{RESET} {status_color}{resp.status_code}{RESET}  {DIM}{truncated}{RESET}")
        except Exception:
            text = resp.text[:200] if resp.text else "(empty)"
            tee(f"    {MAGENTA}<{RESET} {status_color}{resp.status_code}{RESET}  {DIM}{text}{RESET}")

    return resp


def decode(token):
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ============================================================
# DATABASE HELPERS
# ============================================================
def db():
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    conn.autocommit = False
    return conn


def seed_bootstrap_data():
    """Ensure org 'acme' with admin role + admin user exist."""
    conn = db()
    cur = conn.cursor()
    try:
        cur.execute("SET search_path TO authz, public;")

        # Ensure audit_log table exists (may be missing if DB volume predates it)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
                actor_email VARCHAR(255) NOT NULL,
                platform    VARCHAR(50) NOT NULL,
                org_name    VARCHAR(100),
                action      VARCHAR(50) NOT NULL,
                target_type VARCHAR(50) NOT NULL,
                target_id   UUID,
                details     JSONB,
                ip_address  VARCHAR(45)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_platform_org ON audit_log(platform, org_name)")

        # org
        cur.execute("SELECT id FROM mlops_orgs WHERE name = %s", (ORG_NAME,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO mlops_orgs (name) VALUES (%s) RETURNING id", (ORG_NAME,)
            )
            row = cur.fetchone()
            info(f"Created org '{ORG_NAME}'")
        org_id = row[0]

        # admin role
        cur.execute(
            "SELECT id FROM mlops_roles WHERE org_id = %s AND name = 'admin'",
            (org_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO mlops_roles (org_id, name, global_access, bu_access) "
                "VALUES (%s, 'admin', true, true) RETURNING id",
                (org_id,),
            )
            row = cur.fetchone()
            info("Created admin role")
        admin_role_id = row[0]

        # viewer role (needed for some tests)
        cur.execute(
            "SELECT id FROM mlops_roles WHERE org_id = %s AND name = 'viewer'",
            (org_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO mlops_roles (org_id, name, global_access, bu_access) "
                "VALUES (%s, 'viewer', false, false) RETURNING id",
                (org_id,),
            )
            row = cur.fetchone()
            info("Created viewer role")
        viewer_role_id = row[0]

        # permissions for admin
        for resource in ("projects", "pipelines", "experiments"):
            cur.execute(
                "INSERT INTO mlops_perms (role_id, resource, can_read, can_write, can_delete) "
                "VALUES (%s, %s, true, true, true) "
                "ON CONFLICT (role_id, resource) DO NOTHING",
                (admin_role_id, resource),
            )

        # permissions for viewer
        for resource in ("projects", "pipelines", "experiments"):
            cur.execute(
                "INSERT INTO mlops_perms (role_id, resource, can_read, can_write, can_delete) "
                "VALUES (%s, %s, true, false, false) "
                "ON CONFLICT (role_id, resource) DO NOTHING",
                (viewer_role_id, resource),
            )

        # admin user
        cur.execute(
            "SELECT id FROM mlops_users WHERE email = %s", (ADMIN_EMAIL,)
        )
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO mlops_users (email, org_id, role_id, user_uid, is_org_admin) "
                "VALUES (%s, %s, %s, 'admin-uid-001', true)",
                (ADMIN_EMAIL, org_id, admin_role_id),
            )
            info(f"Created admin user {ADMIN_EMAIL}")

        conn.commit()
        return str(org_id)
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def cleanup_previous_run():
    """Remove test user and test roles from a previous run."""
    conn = db()
    cur = conn.cursor()
    try:
        cur.execute("SET search_path TO authz, public;")
        cur.execute("DELETE FROM mlops_users WHERE email = %s", (TEST_USER_EMAIL,))
        # Clean up both the original and renamed role names
        for role_name in ("test-e2e-role", "test-e2e-role-updated"):
            cur.execute(
                "DELETE FROM mlops_perms WHERE role_id IN "
                "(SELECT id FROM mlops_roles WHERE name = %s)",
                (role_name,),
            )
            cur.execute("DELETE FROM mlops_roles WHERE name = %s", (role_name,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ============================================================
# OPA HELPERS
# ============================================================
def opa_query(path, input_data):
    try:
        resp = requests.post(
            f"{OPA_URL}/v1/data/{path}",
            json={"input": input_data},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json().get("result")
    except Exception:
        pass
    return None


def opa_data(path):
    try:
        resp = requests.get(f"{OPA_URL}/v1/data/{path}", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("result")
    except Exception:
        pass
    return None


def poll_opa(description, check_fn, debug_path=None, max_wait=CDC_POLL_MAX_WAIT):
    """Poll OPA until check_fn() returns True."""
    info(f"Polling OPA: {description} (up to {max_wait}s)")
    for i in range(max_wait):
        if check_fn():
            ok(f"CDC synced in {i + 1}s — {description}")
            return True
        if i > 0 and i % 5 == 0:
            info(f"  still waiting... ({i}s)")
            if debug_path:
                snapshot = opa_data(debug_path)
                info(f"  OPA {debug_path} = {json.dumps(snapshot, default=str)[:200] if snapshot else 'null'}")
        time.sleep(CDC_POLL_INTERVAL)
    if debug_path:
        snapshot = opa_data(debug_path)
        info(f"  Final OPA state: {json.dumps(snapshot, default=str)[:300] if snapshot else 'null'}")
    fail(f"CDC timeout after {max_wait}s — {description}")
    return False


# ============================================================
# PHASE 0 — BOOTSTRAP
# ============================================================
def phase_0_bootstrap():
    phase(0, "BOOTSTRAP")

    # Health checks
    step("Health checks")
    for name, url in [
        ("Auth Server", f"{AUTH_SERVER_URL}/health"),
        ("OPA", f"{OPA_URL}/health"),
    ]:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                ok(f"{name} healthy")
            else:
                fail(f"{name} returned {r.status_code}")
                return None, None
        except Exception as e:
            fail(f"{name} unreachable: {e}")
            return None, None

    step("PostgreSQL connection")
    try:
        conn = db()
        conn.close()
        ok("PostgreSQL reachable")
    except Exception as e:
        fail(f"PostgreSQL unreachable: {e}")
        return None, None

    # Seed data
    step("Seed bootstrap data (org, roles, admin user)")
    org_id = seed_bootstrap_data()
    ok(f"Bootstrap data ready (org_id={org_id})")

    # Remove leftovers from previous runs
    step("Clean up leftover test data (user + roles)")
    cleanup_previous_run()
    ok("Cleaned up previous test artifacts")

    # Wait for OPA sync
    step("Wait for admin user to appear in OPA")
    synced = poll_opa(
        "admin user in OPA",
        lambda: opa_query("authz/user_exists", {"user": ADMIN_EMAIL}) is True,
    )
    if not synced:
        info("Trying manual OPA data push as fallback...")
        # The sync-worker initial sync might not have run yet; wait more
        time.sleep(10)
        if opa_query("authz/user_exists", {"user": ADMIN_EMAIL}) is not True:
            fail("Admin user never appeared in OPA — is sync-worker running?")
            return None, None
        ok("Admin user appeared after extended wait")

    # Get admin token via test-login
    step("Get admin token via /test-login")
    resp = api("post", "/api/v1/auth/test-login", json={
        "platform": PLATFORM,
        "org_name": ORG_NAME,
        "email": ADMIN_EMAIL,
    })
    if resp.status_code != 200:
        fail(f"test-login failed: {resp.status_code} — {resp.text}")
        return None, None

    tokens = resp.json()
    admin_token = tokens["access_token"]
    ok(f"Admin token obtained for {tokens['email']}")

    # Resolve org_id via management API
    step("Resolve org_id via GET /manage/orgs")
    resp = api("get", "/api/v1/manage/orgs", token=admin_token)
    if resp.status_code != 200:
        fail(f"List orgs failed: {resp.status_code}")
        return None, None

    orgs = resp.json()["orgs"]
    target_org = next((o for o in orgs if o["name"] == ORG_NAME), None)
    if not target_org:
        fail(f"Org '{ORG_NAME}' not found in API response")
        return None, None

    org_id = target_org["id"]
    ok(f"Org '{ORG_NAME}' id = {org_id}")

    return admin_token, org_id


# ============================================================
# PHASE 1 — CREATE ROLE
# ============================================================
def phase_1_create(admin_token, org_id):
    phase(1, "CREATE ROLE")

    # 1.1 Create role
    step("POST /manage/orgs/{org_id}/roles — create 'test-e2e-role'")
    resp = api("post", f"/api/v1/manage/orgs/{org_id}/roles", token=admin_token, json={
        "name": "test-e2e-role",
        "global_access": False,
        "bu_access": True,
    })
    if resp.status_code != 201:
        fail(f"Create role failed: {resp.status_code} — {resp.text}")
        return None
    role_data = resp.json()
    role_id = role_data["id"]
    ok(f"Role created: id={role_id}, name={role_data['name']}")
    detail("global_access", role_data["global_access"])
    detail("bu_access", role_data["bu_access"])

    # 1.2 CDC: role appears in OPA
    step("CDC — wait for role to appear in OPA RBAC bundle")
    poll_opa(
        "role in OPA RBAC",
        lambda: (
            (d := opa_data(f"rbac/{PLATFORM}/{ORG_NAME}")) is not None
            and "test-e2e-role" in (d or {})
        ),
        debug_path=f"rbac/{PLATFORM}/{ORG_NAME}",
    )

    # 1.3 Set permissions on role
    step("PUT permissions — projects(rw), pipelines(r)")
    resp = api(
        "put",
        f"/api/v1/manage/orgs/{org_id}/roles/{role_id}/permissions",
        token=admin_token,
        json={
            "permissions": [
                {"resource": "projects", "can_read": True, "can_write": True, "can_delete": False},
                {"resource": "pipelines", "can_read": True, "can_write": False, "can_delete": False},
            ]
        },
    )
    if resp.status_code != 200:
        fail(f"Set permissions failed: {resp.status_code} — {resp.text}")
        return None
    perm_data = resp.json()
    ok(f"Permissions set: {perm_data['total']} resources")
    json_detail("permissions", perm_data["permissions"])

    # 1.4 CDC: permissions appear in OPA
    step("CDC — wait for permissions in OPA")
    poll_opa(
        "permissions in OPA",
        lambda: (
            (rd := opa_data(f"rbac/{PLATFORM}/{ORG_NAME}/test-e2e-role")) is not None
            and "projects" in (rd or {})
        ),
        debug_path=f"rbac/{PLATFORM}/{ORG_NAME}/test-e2e-role",
    )

    # 1.5 Add test user with this role
    step(f"POST /manage/orgs/{{org_id}}/users — add '{TEST_USER_EMAIL}' with test-e2e-role")
    resp = api("post", f"/api/v1/manage/orgs/{org_id}/users", token=admin_token, json={
        "email": TEST_USER_EMAIL,
        "role_name": "test-e2e-role",
        "user_uid": TEST_USER_UID,
        "is_org_admin": False,
    })
    if resp.status_code != 201:
        fail(f"Add user failed: {resp.status_code} — {resp.text}")
        return None
    user_data = resp.json()
    user_id = user_data["id"]
    ok(f"User added: id={user_id}, role={user_data['role_name']}")

    # 1.6 CDC: user appears in OPA
    step("CDC — wait for test user in OPA")
    poll_opa(
        "test user in OPA",
        lambda: opa_query("authz/user_exists", {"user": TEST_USER_EMAIL}) is True,
        debug_path="users/user_roles",
    )

    # 1.7 Token: login as test user and verify JWT permissions
    step("Login as test user via /test-login")
    resp = api("post", "/api/v1/auth/test-login", json={
        "platform": PLATFORM,
        "org_name": ORG_NAME,
        "email": TEST_USER_EMAIL,
    })
    if resp.status_code != 200:
        fail(f"Test user login failed: {resp.status_code} — {resp.text}")
        return None, None

    user_tokens = resp.json()
    user_access = user_tokens["access_token"]
    user_refresh = user_tokens["refresh_token"]
    claims = decode(user_access)

    ok("Test user logged in")
    json_detail("JWT permissions", claims.get("permissions", {}))

    perms = claims.get("permissions", {})
    if perms.get("projects", {}).get("write") is True:
        ok("JWT has projects.write=true (correct for test-e2e-role)")
    else:
        fail("JWT missing projects.write=true")

    if perms.get("pipelines", {}).get("write") is not True:
        ok("JWT has pipelines.write=false (correct — read only)")
    else:
        fail("JWT unexpectedly has pipelines.write=true")

    if perms.get("bu_access") is True:
        ok("JWT has bu_access=true (correct)")
    else:
        fail("JWT missing bu_access=true")

    if perms.get("global_access") is not True:
        ok("JWT has global_access=false (correct)")
    else:
        fail("JWT unexpectedly has global_access=true")

    return role_id, user_id, user_refresh


# ============================================================
# PHASE 2 — READ ROLE
# ============================================================
def phase_2_read(admin_token, org_id, role_id):
    phase(2, "READ ROLE")

    # 2.1 List roles
    step("GET /manage/orgs/{org_id}/roles — list roles")
    resp = api("get", f"/api/v1/manage/orgs/{org_id}/roles", token=admin_token)
    if resp.status_code != 200:
        fail(f"List roles failed: {resp.status_code}")
        return
    roles = resp.json()
    role_names = [r["name"] for r in roles["roles"]]
    if "test-e2e-role" in role_names:
        ok(f"Role list contains 'test-e2e-role' (total={roles['total']})")
    else:
        fail("Role 'test-e2e-role' not in list")

    # 2.2 Get role detail
    step("GET /manage/orgs/{org_id}/roles/{role_id} — role detail")
    resp = api("get", f"/api/v1/manage/orgs/{org_id}/roles/{role_id}", token=admin_token)
    if resp.status_code != 200:
        fail(f"Get role detail failed: {resp.status_code}")
        return
    detail_data = resp.json()
    ok(f"Role detail retrieved: {detail_data['name']}")
    if len(detail_data.get("permissions", [])) == 2:
        ok("Detail includes 2 permissions (projects, pipelines)")
    else:
        fail(f"Expected 2 permissions, got {len(detail_data.get('permissions', []))}")
    json_detail("role detail", detail_data)

    # 2.3 Get permissions
    step("GET /manage/orgs/{org_id}/roles/{role_id}/permissions")
    resp = api(
        "get",
        f"/api/v1/manage/orgs/{org_id}/roles/{role_id}/permissions",
        token=admin_token,
    )
    if resp.status_code != 200:
        fail(f"Get permissions failed: {resp.status_code}")
        return
    perm_data = resp.json()
    ok(f"Permissions retrieved: {perm_data['total']} resources for role '{perm_data['role_name']}'")
    json_detail("permissions", perm_data["permissions"])


# ============================================================
# PHASE 3 — UPDATE ROLE
# ============================================================
def phase_3_update(admin_token, org_id, role_id, user_refresh):
    phase(3, "UPDATE ROLE")

    # 3.1 Update role metadata
    step("PUT /manage/orgs/{org_id}/roles/{role_id} — rename + flip global_access")
    resp = api(
        "put",
        f"/api/v1/manage/orgs/{org_id}/roles/{role_id}",
        token=admin_token,
        json={
            "name": "test-e2e-role-updated",
            "global_access": True,
        },
    )
    if resp.status_code != 200:
        fail(f"Update role failed: {resp.status_code} — {resp.text}")
        return
    updated = resp.json()
    if updated["name"] == "test-e2e-role-updated":
        ok("Role renamed to 'test-e2e-role-updated'")
    else:
        fail(f"Expected name 'test-e2e-role-updated', got '{updated['name']}'")
    if updated["global_access"] is True:
        ok("global_access flipped to true")
    else:
        fail("global_access not updated")

    # 3.2 CDC: role metadata update in OPA
    step("CDC — wait for role metadata update in OPA")
    poll_opa(
        "updated role in OPA",
        lambda: (
            (rd := opa_data(f"rbac/{PLATFORM}/{ORG_NAME}/test-e2e-role-updated")) is not None
            and (rd or {}).get("global_access") is True
        ),
        debug_path=f"rbac/{PLATFORM}/{ORG_NAME}",
    )

    # 3.3 Update permissions: add experiments, remove pipelines
    step("PUT permissions — add experiments(rwd), keep projects(rw)")
    resp = api(
        "put",
        f"/api/v1/manage/orgs/{org_id}/roles/{role_id}/permissions",
        token=admin_token,
        json={
            "permissions": [
                {"resource": "projects", "can_read": True, "can_write": True, "can_delete": False},
                {"resource": "experiments", "can_read": True, "can_write": True, "can_delete": True},
            ]
        },
    )
    if resp.status_code != 200:
        fail(f"Update permissions failed: {resp.status_code}")
        return
    ok("Permissions upserted (projects + experiments)")

    step("DELETE permission — remove pipelines")
    resp = api(
        "delete",
        f"/api/v1/manage/orgs/{org_id}/roles/{role_id}/permissions/pipelines",
        token=admin_token,
    )
    if resp.status_code == 204:
        ok("Pipelines permission deleted")
    else:
        fail(f"Delete pipelines permission: {resp.status_code} — {resp.text}")

    # 3.4 CDC: permissions update in OPA
    step("CDC — wait for updated permissions in OPA")
    poll_opa(
        "experiments in OPA + pipelines gone",
        lambda: (
            (rd := opa_data(f"rbac/{PLATFORM}/{ORG_NAME}/test-e2e-role-updated"))
            is not None
            and "experiments" in (rd or {})
            and "pipelines" not in (rd or {})
        ),
        debug_path=f"rbac/{PLATFORM}/{ORG_NAME}/test-e2e-role-updated",
    )

    # Capture pre-refresh permissions from OPA for comparison
    pre_refresh_opa = opa_data(f"rbac/{PLATFORM}/{ORG_NAME}/test-e2e-role-updated")
    info("OPA role state before token refresh:")
    json_detail("OPA permissions", pre_refresh_opa)

    # 3.5 Token refresh: verify new permissions in JWT
    step("Refresh token via /auth/refresh")

    # First, show the OLD token's permissions for comparison
    old_claims = decode(
        api("post", "/api/v1/auth/test-login", log=False, json={
            "platform": PLATFORM, "org_name": ORG_NAME, "email": TEST_USER_EMAIL,
        }).json()["access_token"]
    )
    old_perms = old_claims.get("permissions", {})

    resp = api("post", "/api/v1/auth/refresh", json={"refresh_token": user_refresh})
    if resp.status_code != 200:
        fail(f"Token refresh failed: {resp.status_code} — {resp.text}")
        return
    new_access = resp.json()["access_token"]
    ok("Token refreshed successfully")

    claims = decode(new_access)
    perms = claims.get("permissions", {})

    step("Permission comparison — before vs after refresh")
    comparison("before update", old_perms, "after refresh", perms)

    if perms.get("global_access") is True:
        ok("Refreshed JWT has global_access=true")
    else:
        fail("Refreshed JWT missing global_access=true")

    if "experiments" in perms:
        ok("Refreshed JWT has 'experiments' permission")
    else:
        fail("Refreshed JWT missing 'experiments' permission")

    if perms.get("experiments", {}).get("delete") is True:
        ok("Refreshed JWT has experiments.delete=true")
    else:
        fail("Refreshed JWT missing experiments.delete=true")

    if "pipelines" not in perms:
        ok("Refreshed JWT no longer has 'pipelines' (removed)")
    else:
        fail("Refreshed JWT still has 'pipelines' — should have been removed")


# ============================================================
# PHASE 4 — DELETE
# ============================================================
def phase_4_delete(admin_token, org_id, role_id, user_id):
    phase(4, "DELETE")

    # 4.1 Delete user
    step(f"DELETE /manage/orgs/{{org_id}}/users/{user_id}")
    resp = api(
        "delete",
        f"/api/v1/manage/orgs/{org_id}/users/{user_id}",
        token=admin_token,
    )
    if resp.status_code == 204:
        ok("User deleted")
    else:
        fail(f"Delete user: {resp.status_code} — {resp.text}")

    # 4.2 CDC: user disappears from OPA
    step("CDC — wait for user to disappear from OPA")
    poll_opa(
        "test user gone from OPA",
        lambda: opa_query("authz/user_exists", {"user": TEST_USER_EMAIL}) is not True,
        debug_path="users/user_roles",
    )

    # 4.3 Delete role
    step(f"DELETE /manage/orgs/{{org_id}}/roles/{role_id}")
    resp = api(
        "delete",
        f"/api/v1/manage/orgs/{org_id}/roles/{role_id}",
        token=admin_token,
    )
    if resp.status_code == 204:
        ok("Role deleted")
    else:
        fail(f"Delete role: {resp.status_code} — {resp.text}")

    # 4.4 CDC: role disappears from OPA
    step("CDC — wait for role to disappear from OPA RBAC bundle")
    poll_opa(
        "role gone from OPA",
        lambda: (
            (d := opa_data(f"rbac/{PLATFORM}/{ORG_NAME}")) is not None
            and "test-e2e-role-updated" not in (d or {})
        ),
        debug_path=f"rbac/{PLATFORM}/{ORG_NAME}",
    )

    # 4.5 Verify deleted user can't login
    step("Verify deleted user cannot /test-login")
    resp = api("post", "/api/v1/auth/test-login", json={
        "platform": PLATFORM,
        "org_name": ORG_NAME,
        "email": TEST_USER_EMAIL,
    })
    if resp.status_code == 403:
        ok("Deleted user correctly denied login (403)")
    else:
        fail(f"Expected 403 for deleted user, got {resp.status_code}")


# ============================================================
# PHASE 5 — NEGATIVE CASES
# ============================================================
def phase_5_negative(admin_token, org_id):
    phase(5, "NEGATIVE CASES")

    # 5.1 Duplicate role name
    step("Create role with duplicate name → expect 409")
    # 'admin' already exists
    resp = api("post", f"/api/v1/manage/orgs/{org_id}/roles", token=admin_token, json={
        "name": "admin",
    })
    if resp.status_code == 409:
        ok("Duplicate role name correctly rejected (409)")
    else:
        fail(f"Expected 409 for duplicate role, got {resp.status_code}")

    # 5.2 Delete role that has users → expect 409
    step("Delete role that still has users → expect 409")
    # Get admin role id (has the admin user)
    admin_role = None
    resp = api("get", f"/api/v1/manage/orgs/{org_id}/roles", token=admin_token)
    if resp.status_code == 200:
        admin_role = next(
            (r for r in resp.json()["roles"] if r["name"] == "admin"), None
        )
        if admin_role:
            resp = api(
                "delete",
                f"/api/v1/manage/orgs/{org_id}/roles/{admin_role['id']}",
                token=admin_token,
            )
            if resp.status_code == 409:
                ok("Delete role with users correctly rejected (409)")
            else:
                fail(f"Expected 409 for role with users, got {resp.status_code}")
        else:
            fail("Could not find admin role for negative test")
    else:
        fail(f"List roles failed: {resp.status_code}")

    # 5.3 Update role with empty body → expect 400
    step("Update role with no fields → expect 400")
    if admin_role:
        resp = api(
            "put",
            f"/api/v1/manage/orgs/{org_id}/roles/{admin_role['id']}",
            token=admin_token,
            json={},
        )
        if resp.status_code == 400:
            ok("Empty update correctly rejected (400)")
        else:
            fail(f"Expected 400 for empty update, got {resp.status_code}")
    else:
        fail("Skipped — admin role not found in previous step")

    # 5.4 Non-admin token → expect 403
    step("Access management API without org-admin token → expect 403")
    # Create a non-admin token manually
    now = datetime.now(timezone.utc)
    non_admin_claims = {
        "email": "nobody@acme.com",
        "userID": "nobody-uid",
        "organization": ORG_NAME,
        "platform": PLATFORM,
        "org_admin": 0,
        "permissions": {},
        "licence": {},
        "iat": now,
        "exp": now + timedelta(hours=1),
        "type": "access",
    }
    non_admin_token = jwt.encode(non_admin_claims, SECRET_KEY, algorithm=ALGORITHM)

    resp = api("get", f"/api/v1/manage/orgs", token=non_admin_token)
    if resp.status_code == 403:
        ok("Non-admin correctly denied (403)")
    else:
        fail(f"Expected 403 for non-admin, got {resp.status_code}")

    # 5.5 Get non-existent role → expect 404
    step("Get non-existent role → expect 404")
    fake_id = str(uuid.uuid4())
    resp = api(
        "get",
        f"/api/v1/manage/orgs/{org_id}/roles/{fake_id}",
        token=admin_token,
    )
    if resp.status_code == 404:
        ok("Non-existent role correctly returns 404")
    else:
        fail(f"Expected 404 for non-existent role, got {resp.status_code}")


# ============================================================
# MAIN
# ============================================================
def run():
    global start_time
    start_time = time.time()

    log_path = _init_log_file()

    banner("E2E Test: Role CRUD + CDC Pipeline + Token Refresh")
    tee(f"  {DIM}Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    tee(f"  {DIM}Auth Server: {AUTH_SERVER_URL}{RESET}")
    tee(f"  {DIM}OPA:         {OPA_URL}{RESET}")
    tee(f"  {DIM}Platform:    {PLATFORM}{RESET}")
    tee(f"  {DIM}Org:         {ORG_NAME}{RESET}")
    tee(f"  {DIM}Log file:    {log_path}{RESET}")

    # Phase 0
    result = phase_0_bootstrap()
    if result is None or result[0] is None:
        banner("BOOTSTRAP FAILED — ABORTING", "!")
        _close_log_file()
        return False
    admin_token, org_id = result

    # Phase 1
    result = phase_1_create(admin_token, org_id)
    if result is None:
        banner("CREATE PHASE FAILED — ABORTING", "!")
        _close_log_file()
        return False
    role_id, user_id, user_refresh = result

    # Phase 2
    phase_2_read(admin_token, org_id, role_id)

    # Phase 3
    phase_3_update(admin_token, org_id, role_id, user_refresh)

    # Phase 4
    phase_4_delete(admin_token, org_id, role_id, user_id)

    # Phase 5
    phase_5_negative(admin_token, org_id)

    # Summary
    elapsed = time.time() - start_time
    banner("TEST SUMMARY")
    total = passed + failed
    tee(f"  {GREEN}Passed:{RESET}  {passed}")
    tee(f"  {RED}Failed:{RESET}  {failed}")
    tee(f"  Total:   {total}")
    tee(f"  Elapsed: {elapsed:.1f}s")

    if errors:
        tee(f"\n  {RED}{BOLD}Failures:{RESET}")
        for i, e in enumerate(errors, 1):
            tee(f"    {RED}{i}. {e}{RESET}")

    tee(f"\n  Log written to: {log_path}")

    if failed == 0:
        banner("ALL TESTS PASSED", "=")
        _close_log_file()
        return True
    else:
        banner(f"{failed} TEST(S) FAILED", "!")
        _close_log_file()
        return False


if __name__ == "__main__":
    try:
        success = run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        tee("\n\nTest interrupted")
        _close_log_file()
        sys.exit(1)
    except Exception as e:
        tee(f"\n{RED}Unexpected error: {e}{RESET}")
        import traceback
        traceback.print_exc()
        _close_log_file()
        sys.exit(1)
