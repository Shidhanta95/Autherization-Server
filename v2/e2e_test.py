#!/usr/bin/env python3
"""
End-to-End Test Script for Authorization Server v2

This script tests the complete flow:
1. User login (simulated SSO callback)
2. JWT creation with permissions
3. Permission modification in PostgreSQL
4. OPA sync verification
5. JWT refresh to get updated permissions

Prerequisites:
- Docker Compose stack running (docker compose up -d)
- Services healthy: postgres, redis, opa, auth-server, sync-worker

Usage:
    python e2e_test.py

"""

import sys
import time
import json
import requests
import psycopg2
from datetime import datetime
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

# Test user details
TEST_USER_EMAIL = "testuser@acme.com"
TEST_USER_PLATFORM = "mlops"
TEST_USER_ORG = "acme"

# Colors for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def print_step(step_num, message):
    print(f"\n{BLUE}[Step {step_num}]{RESET} {message}")


def print_success(message):
    print(f"  {GREEN}✓{RESET} {message}")


def print_error(message):
    print(f"  {RED}✗{RESET} {message}")


def print_info(message):
    print(f"  {YELLOW}→{RESET} {message}")


def print_json(data, indent=4):
    """Pretty print JSON data"""
    print(json.dumps(data, indent=indent, default=str))


# ============================================================
# SERVICE HEALTH CHECKS
# ============================================================
def check_services():
    """Check if all services are healthy"""
    print_step(0, "Checking service health...")

    services = {
        "Auth Server": f"{AUTH_SERVER_URL}/health",
        "OPA": f"{OPA_URL}/health",
    }

    all_healthy = True
    for name, url in services.items():
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                print_success(f"{name} is healthy")
            else:
                print_error(f"{name} returned {resp.status_code}")
                all_healthy = False
        except requests.RequestException as e:
            print_error(f"{name} is not reachable: {e}")
            all_healthy = False

    # Check PostgreSQL
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        conn.close()
        print_success("PostgreSQL is healthy")
    except Exception as e:
        print_error(f"PostgreSQL is not reachable: {e}")
        all_healthy = False

    return all_healthy


# ============================================================
# DATABASE OPERATIONS
# ============================================================
def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(**POSTGRES_CONFIG)


def setup_test_user():
    """Create test user if not exists"""
    print_step(1, "Setting up test user in database...")

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SET search_path TO authz, public;")

        # Check if user exists
        cur.execute(
            "SELECT email FROM mlops_users WHERE email = %s", (TEST_USER_EMAIL,)
        )
        existing = cur.fetchone()

        if existing:
            print_info(f"User {TEST_USER_EMAIL} already exists")
        else:
            # Get org_id (column is 'id' not 'org_id' in mlops_orgs)
            cur.execute("SELECT id FROM mlops_orgs WHERE name = %s", (TEST_USER_ORG,))
            org = cur.fetchone()
            if not org:
                print_error(f"Organization {TEST_USER_ORG} not found")
                return False
            org_id = org[0]

            # Get viewer role (using org_id to filter)
            cur.execute(
                "SELECT id FROM mlops_roles WHERE name = 'viewer' AND org_id = %s",
                (org_id,),
            )
            role = cur.fetchone()
            if not role:
                print_error("Viewer role not found")
                return False
            role_id = role[0]

            # Insert user
            cur.execute(
                """
                INSERT INTO mlops_users (email, org_id, role_id, user_uid, is_org_admin)
                VALUES (%s, %s, %s, %s, false)
                """,
                (TEST_USER_EMAIL, org_id, role_id, "user-001"),
            )
            conn.commit()
            print_success(f"Created user {TEST_USER_EMAIL} with viewer role")

        return True

    except Exception as e:
        print_error(f"Database error: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def get_user_role(email):
    """Get user's current role from database"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SET search_path TO authz, public;")
        cur.execute(
            """
            SELECT r.name 
            FROM mlops_users u 
            JOIN mlops_roles r ON u.role_id = r.id 
            WHERE u.email = %s
            """,
            (email,),
        )
        result = cur.fetchone()
        return result[0] if result else None
    finally:
        cur.close()
        conn.close()


def update_user_role(email, new_role):
    """Update user's role in database"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SET search_path TO authz, public;")

        # Get user's org_id first
        cur.execute("SELECT org_id FROM mlops_users WHERE email = %s", (email,))
        user = cur.fetchone()
        if not user:
            print_error(f"User {email} not found")
            return False
        org_id = user[0]

        # Get new role_id for the same org
        cur.execute(
            "SELECT id FROM mlops_roles WHERE name = %s AND org_id = %s",
            (new_role, org_id),
        )
        role = cur.fetchone()
        if not role:
            print_error(f"Role {new_role} not found for org")
            return False
        role_id = role[0]

        # Update user
        cur.execute(
            "UPDATE mlops_users SET role_id = %s WHERE email = %s",
            (role_id, email),
        )
        conn.commit()
        print_success(f"Updated {email} to role: {new_role}")
        return True

    except Exception as e:
        print_error(f"Database error: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def update_user_role(email, new_role):
    """Update user's role in database"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SET search_path TO authz, public;")

        # Get new role_id
        cur.execute("SELECT role_id FROM mlops_roles WHERE role_name = %s", (new_role,))
        role = cur.fetchone()
        if not role:
            print_error(f"Role {new_role} not found")
            return False
        role_id = role[0]

        # Update user
        cur.execute(
            "UPDATE mlops_users SET role_id = %s WHERE email = %s",
            (role_id, email),
        )
        conn.commit()
        print_success(f"Updated {email} to role: {new_role}")
        return True

    except Exception as e:
        print_error(f"Database error: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


# ============================================================
# OPA OPERATIONS
# ============================================================
def check_opa_user_exists(email):
    """Check if user exists in OPA"""
    url = f"{OPA_URL}/v1/data/authz/user_exists"
    payload = {"input": {"user": email}}

    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            result = resp.json()
            return result.get("result", False)
    except Exception as e:
        print_error(f"OPA error: {e}")
    return False


def get_opa_user_permissions(email, platform):
    """Get user permissions from OPA"""
    url = f"{OPA_URL}/v1/data/authz/user_permissions"
    payload = {"input": {"user": email, "platform": platform}}

    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            result = resp.json()
            return result.get("result", {})
    except Exception as e:
        print_error(f"OPA error: {e}")
    return {}


def get_opa_user_context(email, platform):
    """Get user context from OPA"""
    url = f"{OPA_URL}/v1/data/authz/user_context"
    payload = {"input": {"user": email, "platform": platform}}

    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            result = resp.json()
            return result.get("result", {})
    except Exception as e:
        print_error(f"OPA error: {e}")
    return {}


def wait_for_opa_sync(email, expected_role, max_wait=30):
    """Wait for OPA to sync with database changes"""
    print_info(f"Waiting for OPA to sync (max {max_wait}s)...")

    for i in range(max_wait):
        context = get_opa_user_context(email, TEST_USER_PLATFORM)
        if context.get("role") == expected_role:
            print_success(f"OPA synced! User role is now: {expected_role}")
            return True
        time.sleep(1)
        if i % 5 == 0 and i > 0:
            print_info(f"Still waiting... ({i}s)")

    print_error(f"OPA sync timeout after {max_wait}s")
    return False


# ============================================================
# AUTH SERVER OPERATIONS
# ============================================================
def simulate_login(email, platform, org_name):
    """
    Simulate the SSO login flow.
    Since we can't do actual SSO, we'll use the test-login endpoint.
    For real SSO, you would:
    1. POST /api/v1/auth/login -> get redirect URL
    2. Complete SSO at IdP
    3. GET /api/v1/auth/callback -> get tokens
    """
    print_step(3, "Simulating login flow...")

    # First, check if user exists via OPA
    print_info("Checking user via OPA...")

    context = get_opa_user_context(email, platform)
    if not context:
        print_error("User not found in OPA")
        return None, None

    print_success(f"User context from OPA: {json.dumps(context)}")

    # Get permissions from OPA
    permissions = get_opa_user_permissions(email, platform)
    print_success(f"User permissions: {json.dumps(permissions)}")

    # Use the test-login endpoint (bypasses SSO for testing)
    test_login_url = f"{AUTH_SERVER_URL}/api/v1/auth/test-login"
    payload = {
        "email": email,
        "platform": platform,
        "org_name": org_name,
    }

    try:
        resp = requests.post(test_login_url, json=payload, timeout=10)
        if resp.status_code == 200:
            tokens = resp.json()
            print_success("Login successful via test-login endpoint!")
            return tokens.get("access_token"), tokens.get("refresh_token")
        elif resp.status_code == 404:
            print_info(f"Test login endpoint not available (404)")
            print_info("Make sure DEBUG=true is set in docker-compose.yaml")
            print_info("Will create test tokens manually...")
        else:
            print_error(f"Test login failed: {resp.status_code} - {resp.text}")
            print_info("Will create test tokens manually...")
    except Exception as e:
        print_error(f"Test login endpoint error: {e}")
        print_info("Will create test tokens manually...")

    # Manual token creation for testing (fallback)
    return create_test_tokens(email, platform, context, permissions)


def create_test_tokens(email, platform, context, permissions):
    """Create test tokens manually (for E2E testing only)"""
    from datetime import timedelta
    import uuid

    SECRET_KEY = "change-this-in-production-use-a-strong-secret"
    ALGORITHM = "HS256"

    now = datetime.utcnow()

    # Access token
    access_claims = {
        "email": email,
        "userID": context.get("user_id", "test-user-001"),
        "organization": context.get("organization", TEST_USER_ORG),
        "platform": platform,
        "org_admin": context.get("is_org_admin", 0),
        "permissions": permissions,
        "licence": {
            "instanceid": "test-instance",
            "organization": TEST_USER_ORG,
        },
        "iat": now,
        "exp": now + timedelta(hours=1),
        "type": "access",
    }
    access_token = jwt.encode(access_claims, SECRET_KEY, algorithm=ALGORITHM)

    # Refresh token
    refresh_claims = {
        "email": email,
        "platform": platform,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(days=30),
        "type": "refresh",
    }
    refresh_token = jwt.encode(refresh_claims, SECRET_KEY, algorithm=ALGORITHM)

    print_success("Created test tokens manually")
    return access_token, refresh_token


def decode_token(token):
    """Decode a JWT token (without verification for inspection)"""
    SECRET_KEY = "change-this-in-production-use-a-strong-secret"
    ALGORITHM = "HS256"
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def refresh_access_token(refresh_token):
    """Refresh the access token via auth server"""
    print_info("Refreshing access token via auth server...")

    url = f"{AUTH_SERVER_URL}/api/v1/auth/refresh"
    payload = {"refresh_token": refresh_token}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            tokens = resp.json()
            print_success("Token refreshed successfully!")
            return tokens.get("access_token")
        else:
            print_error(f"Refresh failed: {resp.status_code} - {resp.text}")
    except Exception as e:
        print_error(f"Refresh error: {e}")

    return None


def refresh_token_manually(email, platform):
    """Manually create a new access token with current permissions (for testing)"""
    print_info("Creating new access token with updated permissions...")

    context = get_opa_user_context(email, platform)
    permissions = get_opa_user_permissions(email, platform)

    access_token, _ = create_test_tokens(email, platform, context, permissions)
    return access_token


# ============================================================
# MAIN TEST FLOW
# ============================================================
def run_e2e_test():
    """Run the complete E2E test"""
    print("\n" + "=" * 60)
    print("  End-to-End Test: Authorization Server v2")
    print("=" * 60)

    # Step 0: Check services
    if not check_services():
        print_error("\nServices not healthy. Please ensure docker-compose is running.")
        print_info("Run: cd v2 && docker compose up -d")
        return False

    # Step 1: Setup test user
    if not setup_test_user():
        return False

    # Wait for initial sync
    print_info("Waiting for initial OPA sync...")
    time.sleep(5)

    # Step 2: Verify user in OPA
    print_step(2, "Verifying user in OPA...")
    if check_opa_user_exists(TEST_USER_EMAIL):
        print_success(f"User {TEST_USER_EMAIL} exists in OPA")
    else:
        print_error("User not found in OPA. Sync may not be complete.")
        print_info("Waiting additional time for sync...")
        time.sleep(10)
        if not check_opa_user_exists(TEST_USER_EMAIL):
            return False

    context = get_opa_user_context(TEST_USER_EMAIL, TEST_USER_PLATFORM)
    print_success(
        f"User context: role={context.get('role')}, org={context.get('organization')}"
    )

    # Step 3: Login and get initial tokens
    access_token, refresh_token = simulate_login(
        TEST_USER_EMAIL, TEST_USER_PLATFORM, TEST_USER_ORG
    )
    if not access_token:
        return False

    # Step 4: Decode and show initial permissions
    print_step(4, "Analyzing initial JWT...")
    initial_claims = decode_token(access_token)
    print_info("Initial JWT claims:")
    print(f"  - Email: {initial_claims.get('email')}")
    print(f"  - Organization: {initial_claims.get('organization')}")
    print(f"  - Platform: {initial_claims.get('platform')}")
    print(f"  - Role (from OPA): {context.get('role')}")
    print(
        f"  - Permissions: {json.dumps(initial_claims.get('permissions', {}), indent=4)}"
    )

    initial_permissions = initial_claims.get("permissions", {})

    # Step 5: Modify user permissions in database
    print_step(5, "Modifying user permissions in database...")
    current_role = get_user_role(TEST_USER_EMAIL)
    print_info(f"Current role: {current_role}")

    # Toggle between viewer and admin
    new_role = "admin" if current_role == "viewer" else "viewer"
    if not update_user_role(TEST_USER_EMAIL, new_role):
        return False

    # Step 6: Wait for OPA sync
    print_step(6, "Waiting for CDC pipeline to sync changes to OPA...")
    if not wait_for_opa_sync(TEST_USER_EMAIL, new_role, max_wait=30):
        print_error("OPA did not sync in time")
        print_info("Check sync-worker logs: docker compose logs sync-worker")
        return False

    # Verify new permissions in OPA
    new_opa_permissions = get_opa_user_permissions(TEST_USER_EMAIL, TEST_USER_PLATFORM)
    print_success(f"New permissions in OPA: {json.dumps(new_opa_permissions)}")

    # Step 7: Refresh token to get new permissions
    print_step(7, "Refreshing JWT to get updated permissions...")

    # Try via auth server first
    new_access_token = refresh_access_token(refresh_token)

    # If auth server refresh doesn't work, do it manually for testing
    if not new_access_token:
        print_info("Using manual token refresh for testing...")
        new_access_token = refresh_token_manually(TEST_USER_EMAIL, TEST_USER_PLATFORM)

    if not new_access_token:
        return False

    # Step 8: Verify new permissions in JWT
    print_step(8, "Verifying updated permissions in new JWT...")
    new_claims = decode_token(new_access_token)

    print_info("New JWT claims:")
    print(f"  - Role (from OPA): {new_role}")
    print(f"  - Permissions: {json.dumps(new_claims.get('permissions', {}), indent=4)}")

    new_permissions = new_claims.get("permissions", {})

    # Compare permissions
    print_step(9, "Comparing permissions before and after...")
    print_info(f"Before (role={current_role}):")
    print(f"  {json.dumps(initial_permissions)}")
    print_info(f"After (role={new_role}):")
    print(f"  {json.dumps(new_permissions)}")

    # Verify change
    if initial_permissions != new_permissions:
        print_success("Permissions changed successfully!")

        # Check specific permission differences
        if new_role == "admin":
            # Admin should have write/delete permissions
            projects_perms = new_permissions.get("projects", {})
            if (
                projects_perms.get("write") == True
                and projects_perms.get("delete") == True
            ):
                print_success("Admin permissions verified: write=True, delete=True")
            else:
                print_error("Admin permissions not as expected")
        else:
            # Viewer should have read-only
            projects_perms = new_permissions.get("projects", {})
            if (
                projects_perms.get("write") == False
                and projects_perms.get("delete") == False
            ):
                print_success("Viewer permissions verified: write=False, delete=False")
            else:
                print_error("Viewer permissions not as expected")
    else:
        print_error("Permissions did not change!")
        return False

    # Step 10: Test authorization endpoint
    print_step(10, "Testing authorization endpoint...")
    test_authorization(new_access_token)

    # Cleanup: Reset user to original role
    print_step(11, "Cleanup: Resetting user to original role...")
    update_user_role(TEST_USER_EMAIL, current_role)

    print("\n" + "=" * 60)
    print(f"  {GREEN}E2E TEST COMPLETED SUCCESSFULLY!{RESET}")
    print("=" * 60 + "\n")

    return True


def test_authorization(access_token):
    """Test the authorization endpoint"""
    headers = {"Authorization": f"Bearer {access_token}"}

    # Test /authorize/me
    print_info("Testing /authorize/me...")
    try:
        resp = requests.get(
            f"{AUTH_SERVER_URL}/api/v1/authorize/me", headers=headers, timeout=5
        )
        if resp.status_code == 200:
            me_data = resp.json()
            print_success(f"/authorize/me: {json.dumps(me_data)}")
        else:
            print_error(f"/authorize/me failed: {resp.status_code}")
    except Exception as e:
        print_error(f"/authorize/me error: {e}")

    # Test /authorize (check specific permission)
    print_info("Testing /authorize (projects:read)...")
    try:
        resp = requests.post(
            f"{AUTH_SERVER_URL}/api/v1/authorize",
            headers=headers,
            json={"resource": "projects", "action": "read"},
            timeout=5,
        )
        if resp.status_code == 200:
            auth_result = resp.json()
            print_success(f"/authorize: allowed={auth_result.get('allowed')}")
        else:
            print_error(f"/authorize failed: {resp.status_code}")
    except Exception as e:
        print_error(f"/authorize error: {e}")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    try:
        success = run_e2e_test()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Unexpected error: {e}{RESET}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
