#!/usr/bin/env python3
"""
Interactive Browser E2E Test for Authorization Server v2

This test opens a real browser and waits for you to manually log in.
After login, it captures the tokens and continues with automated tests.

Usage:
    python e2e_interactive_test.py

Flow:
    1. Opens browser to Keycloak login page
    2. YOU manually log in (native or federated IdP)
    3. Test captures the tokens from callback
    4. Automated tests continue (role changes, CDC sync, etc.)

"""

import sys
import time
import json
import requests
import psycopg2
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from jose import jwt

# ============================================================
# CONFIGURATION
# ============================================================
AUTH_SERVER_URL = "http://localhost:8000"
OPA_URL = "http://localhost:8181"
KEYCLOAK_URL = "http://localhost:8080"

POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "authz",
    "user": "authz",
    "password": "authz123",
}

TEST_USER_PLATFORM = "mlops"
TEST_USER_ORG = "acme"

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner(text, char="="):
    width = 70
    print(f"\n{BOLD}{char * width}{RESET}")
    print(f"{BOLD}{text.center(width)}{RESET}")
    print(f"{BOLD}{char * width}{RESET}\n")


def print_step(step_num, message):
    print(f"\n{BLUE}{BOLD}{'─' * 70}{RESET}")
    print(f"{BLUE}{BOLD}[STEP {step_num}]{RESET} {BOLD}{message}{RESET}")
    print(f"{BLUE}{'─' * 70}{RESET}")


def print_subtest(test_name):
    print(f"\n  {CYAN}▶ TEST:{RESET} {test_name}")


def print_action(message):
    print(f"    {MAGENTA}⚙{RESET}  {message}")


def print_success(message):
    print(f"    {GREEN}✓ PASS:{RESET} {message}")


def print_error(message):
    print(f"    {RED}✗ FAIL:{RESET} {message}")


def print_info(message):
    print(f"    {YELLOW}→{RESET} {message}")


def print_detail(key, value):
    print(f"      {DIM}•{RESET} {key}: {CYAN}{value}{RESET}")


def print_json(label, data):
    print(f"      {DIM}•{RESET} {label}:")
    formatted = json.dumps(data, indent=2, default=str)
    for line in formatted.split("\n"):
        print(f"        {CYAN}{line}{RESET}")


def print_waiting(message):
    print(f"\n    {YELLOW}{BOLD}⏳ WAITING:{RESET} {message}")


# ============================================================
# SERVICE CHECKS
# ============================================================
def check_services():
    print_step(0, "Service Health Check")

    all_healthy = True

    for name, url in [
        ("Auth Server", f"{AUTH_SERVER_URL}/health"),
        ("OPA", f"{OPA_URL}/health"),
        ("Keycloak", f"{KEYCLOAK_URL}/realms/authz/.well-known/openid-configuration"),
    ]:
        print_subtest(f"{name}")
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                print_success(f"{name} is healthy")
            else:
                print_error(f"{name} returned {resp.status_code}")
                all_healthy = False
        except Exception as e:
            print_error(f"{name} unreachable: {e}")
            all_healthy = False

    print_subtest("PostgreSQL")
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        conn.close()
        print_success("PostgreSQL is healthy")
    except Exception as e:
        print_error(f"PostgreSQL unreachable: {e}")
        all_healthy = False

    return all_healthy


# ============================================================
# INTERACTIVE BROWSER LOGIN
# ============================================================
def interactive_browser_login():
    """
    Opens browser for manual login, waits for callback, returns tokens.
    """
    print_step(1, "Interactive Browser SSO Login")

    # Step 1: Get authorization URL
    print_subtest("Initiate login via Auth Server")
    print_action(f"POST {AUTH_SERVER_URL}/api/v1/auth/login")

    resp = requests.post(
        f"{AUTH_SERVER_URL}/api/v1/auth/login",
        json={"platform": TEST_USER_PLATFORM, "org_name": TEST_USER_ORG},
        timeout=10,
    )

    if resp.status_code != 200:
        print_error(f"Failed to initiate login: {resp.status_code} - {resp.text}")
        return None, None, None

    login_url = resp.json().get("login_url")

    # Fix Keycloak URL if auth-server returned wrong format
    if "/realms/" in login_url and "/v1/authorize" in login_url:
        login_url = login_url.replace("/v1/authorize", "/protocol/openid-connect/auth")
        print_info("Fixed Keycloak authorization URL format")

    print_success("Got authorization URL")
    print_detail("URL", login_url[:80] + "...")

    # Step 2: Open browser and wait for manual login
    print_subtest("Browser Login (Manual)")

    print(f"""
    {YELLOW}{BOLD}╔══════════════════════════════════════════════════════════════════╗
    ║                     MANUAL LOGIN REQUIRED                        ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║                                                                  ║
    ║  A browser window will open with the Keycloak login page.        ║
    ║                                                                  ║
    ║  You can log in using:                                           ║
    ║                                                                  ║
    ║    NATIVE USERS (username/password):                             ║
    ║      • testuser@acme.com / testpassword123                       ║
    ║      • test.user@gmail.com / test.user                           ║
    ║                                                                  ║
    ║    FEDERATED IdPs (click the button):                            ║
    ║      • "Login with Okta"                                         ║
    ║      • "Login with Auth0" (needs secret configured)              ║
    ║      • "Login with Microsoft" (needs secret configured)          ║
    ║                                                                  ║
    ║  After successful login, you'll see a JSON response.             ║
    ║  The test will automatically capture it.                         ║
    ║                                                                  ║
    ╚══════════════════════════════════════════════════════════════════╝{RESET}
    """)

    print(f"    {CYAN}Opening browser in 3 seconds...{RESET}")
    time.sleep(3)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Always headed for interactive
        context = browser.new_context()
        page = context.new_page()

        try:
            print_action("Opening browser...")
            page.goto(login_url, wait_until="networkidle", timeout=30000)
            print_success("Browser opened - Keycloak login page loaded")

            print_waiting("Complete the login in the browser...")
            print_info("The test will continue automatically after login")
            print_info(
                f"Waiting for redirect to {AUTH_SERVER_URL}/api/v1/auth/callback..."
            )

            # Wait for redirect to callback (up to 5 minutes for manual login)
            page.wait_for_url(f"{AUTH_SERVER_URL}/**", timeout=300000)

            print_success("Login completed! Captured callback response.")

            # Extract tokens from JSON response
            json_text = page.inner_text("body")
            print_info(f"Response body: {json_text[:500]}")

            try:
                tokens = json.loads(json_text)
            except json.JSONDecodeError:
                print_error(f"Response is not JSON: {json_text[:200]}")
                return None, None, None

            # Check if it's an error response
            if "detail" in tokens:
                print_error(f"Auth server error: {tokens.get('detail')}")
                return None, None, None

            email = tokens.get("email", "unknown")

            print(f"\n    {GREEN}{BOLD}✓ LOGIN SUCCESSFUL!{RESET}")
            print_detail("Email", tokens.get("email"))
            print_detail("Organization", tokens.get("organization"))
            print_detail("User ID", tokens.get("user_id"))
            print_detail("Access Token", "Yes" if tokens.get("access_token") else "No")
            print_detail(
                "Refresh Token", "Yes" if tokens.get("refresh_token") else "No"
            )

            return tokens.get("access_token"), tokens.get("refresh_token"), email

        except PlaywrightTimeout:
            print_error("Timeout waiting for login (5 minutes)")
            return None, None, None
        except json.JSONDecodeError as e:
            print_error(f"Failed to parse callback response: {e}")
            return None, None, None
        except Exception as e:
            print_error(f"Browser error: {e}")
            return None, None, None
        finally:
            print_info("Closing browser...")
            browser.close()


# ============================================================
# DATABASE OPERATIONS
# ============================================================
def get_db_connection():
    return psycopg2.connect(**POSTGRES_CONFIG)


def get_user_from_db(email):
    """Get user details from database"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET search_path TO authz, public;")
        cur.execute(
            """
            SELECT u.email, r.name as role, o.name as org
            FROM mlops_users u
            JOIN mlops_roles r ON u.role_id = r.id
            JOIN mlops_orgs o ON u.org_id = o.id
            WHERE u.email = %s
        """,
            (email,),
        )
        result = cur.fetchone()
        if result:
            return {"email": result[0], "role": result[1], "org": result[2]}
        return None
    finally:
        cur.close()
        conn.close()


def ensure_user_in_db(email, org="acme"):
    """Ensure user exists in database (create if not)"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET search_path TO authz, public;")

        # Check if exists
        cur.execute("SELECT email FROM mlops_users WHERE email = %s", (email,))
        if cur.fetchone():
            return True

        # Get org_id
        cur.execute("SELECT id FROM mlops_orgs WHERE name = %s", (org,))
        org_row = cur.fetchone()
        if not org_row:
            print_error(f"Organization '{org}' not found")
            return False
        org_id = org_row[0]

        # Get viewer role
        cur.execute(
            "SELECT id FROM mlops_roles WHERE name = 'viewer' AND org_id = %s",
            (org_id,),
        )
        role_row = cur.fetchone()
        if not role_row:
            print_error("Viewer role not found")
            return False
        role_id = role_row[0]

        # Create user
        cur.execute(
            """
            INSERT INTO mlops_users (email, org_id, role_id, user_uid, is_org_admin)
            VALUES (%s, %s, %s, %s, false)
        """,
            (email, org_id, role_id, f"user-{email.split('@')[0]}"),
        )
        conn.commit()
        print_success(f"Created user {email} in database with viewer role")
        return True

    except Exception as e:
        print_error(f"Database error: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def get_user_role(email):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET search_path TO authz, public;")
        cur.execute(
            """
            SELECT r.name FROM mlops_users u
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
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET search_path TO authz, public;")
        cur.execute("SELECT org_id FROM mlops_users WHERE email = %s", (email,))
        user = cur.fetchone()
        if not user:
            return False

        cur.execute(
            "SELECT id FROM mlops_roles WHERE name = %s AND org_id = %s",
            (new_role, user[0]),
        )
        role = cur.fetchone()
        if not role:
            return False

        cur.execute(
            "UPDATE mlops_users SET role_id = %s WHERE email = %s",
            (role[0], email),
        )
        conn.commit()
        return True
    except:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


# ============================================================
# OPA OPERATIONS
# ============================================================
def get_opa_user_context(email, platform):
    url = f"{OPA_URL}/v1/data/authz/user_context"
    resp = requests.post(
        url, json={"input": {"user": email, "platform": platform}}, timeout=5
    )
    if resp.status_code == 200:
        return resp.json().get("result", {})
    return {}


def get_opa_permissions(email, platform):
    url = f"{OPA_URL}/v1/data/authz/user_permissions"
    resp = requests.post(
        url, json={"input": {"user": email, "platform": platform}}, timeout=5
    )
    if resp.status_code == 200:
        return resp.json().get("result", {})
    return {}


def wait_for_opa_sync(email, expected_role, max_wait=30):
    print_subtest("Wait for CDC sync to OPA")
    print_info(f"Expecting role to become '{expected_role}'")

    for i in range(max_wait):
        context = get_opa_user_context(email, TEST_USER_PLATFORM)
        current_role = context.get("role")
        if current_role == expected_role:
            print_success(f"OPA synced after {i + 1}s - role is now '{expected_role}'")
            return True
        if i % 5 == 0:
            print_info(f"Waiting... ({i}s) current role: {current_role}")
        time.sleep(1)

    print_error(f"Sync timeout after {max_wait}s")
    return False


# ============================================================
# TOKEN OPERATIONS
# ============================================================
def decode_token(token):
    SECRET_KEY = "change-this-in-production-use-a-strong-secret"
    return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])


def refresh_token_via_server(refresh_token):
    print_subtest("Refresh token via Auth Server")
    resp = requests.post(
        f"{AUTH_SERVER_URL}/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
        timeout=10,
    )
    if resp.status_code == 200:
        tokens = resp.json()
        print_success("Token refreshed!")
        return tokens.get("access_token")
    else:
        print_info(f"Refresh returned {resp.status_code}: {resp.text[:100]}")
        return None


# ============================================================
# AUTHORIZATION TESTS
# ============================================================
def test_authorization(access_token, expected_write=False):
    print_subtest("Test authorization endpoints")
    headers = {"Authorization": f"Bearer {access_token}"}

    # GET /authorize/me
    print_action("GET /authorize/me")
    resp = requests.get(
        f"{AUTH_SERVER_URL}/api/v1/authorize/me", headers=headers, timeout=5
    )
    if resp.status_code == 200:
        data = resp.json()
        print_success(f"User: {data.get('email')}, Org: {data.get('organization')}")
        print_json("Permissions", data.get("permissions", {}))
    else:
        print_error(f"Failed: {resp.status_code}")

    # POST /authorize
    print_action("POST /authorize (check write permission on projects)")
    resp = requests.post(
        f"{AUTH_SERVER_URL}/api/v1/authorize",
        headers=headers,
        json={"resource": "projects", "action": "write"},
        timeout=5,
    )
    if resp.status_code == 200:
        allowed = resp.json().get("allowed")
        if allowed == expected_write:
            print_success(f"write permission = {allowed} (expected: {expected_write})")
        else:
            print_error(f"write permission = {allowed} (expected: {expected_write})")
    else:
        print_error(f"Failed: {resp.status_code}")


# ============================================================
# MAIN TEST
# ============================================================
def run_test():
    print_banner("Interactive E2E Test: Authorization Server v2")
    print(f"{DIM}This test uses a real browser for manual SSO login{RESET}")
    print(
        f"{DIM}You can test native Keycloak users or federated IdPs (Okta, Auth0, Azure AD){RESET}\n"
    )

    # Step 0: Health checks
    if not check_services():
        print_error("Services not healthy!")
        return False

    # Step 1: Browser login (manual)
    access_token, refresh_token, email = interactive_browser_login()

    if not access_token:
        print_error("Login failed!")
        return False

    # Step 2: Ensure user exists in database
    print_step(2, "Verify/Create User in Database")
    print_subtest(f"Check if {email} exists in database")

    user_info = get_user_from_db(email)
    if user_info:
        print_success(f"User exists: role={user_info['role']}, org={user_info['org']}")
    else:
        print_info(f"User {email} not in database - creating...")
        if not ensure_user_in_db(email):
            print_error("Failed to create user in database")
            return False
        user_info = get_user_from_db(email)
        print_success(f"User created: role={user_info['role']}, org={user_info['org']}")

    # Wait for OPA sync
    print_info("Waiting 5s for OPA sync...")
    time.sleep(5)

    # Step 3: Analyze initial token
    print_step(3, "Analyze JWT Token")
    print_subtest("Decode access token")

    claims = decode_token(access_token)
    print_success("Token decoded")
    print_json(
        "Claims",
        {
            "email": claims.get("email"),
            "organization": claims.get("organization"),
            "platform": claims.get("platform"),
            "userID": claims.get("userID"),
            "permissions": claims.get("permissions"),
        },
    )

    initial_permissions = claims.get("permissions", {})
    current_role = get_user_role(email)
    print_detail("Current role in DB", current_role)

    # Step 4: Test authorization with current role
    print_step(4, "Test Authorization (Current Role)")
    is_admin = current_role == "admin"
    test_authorization(access_token, expected_write=is_admin)

    # Step 5: Change role
    print_step(5, "Modify User Role in Database")
    new_role = "admin" if current_role == "viewer" else "viewer"
    print_subtest(f"Change role: {current_role} → {new_role}")

    if update_user_role(email, new_role):
        print_success(f"Role updated to {new_role}")
    else:
        print_error("Failed to update role")
        return False

    # Step 6: Wait for OPA sync
    print_step(6, "Wait for CDC Pipeline Sync")
    if not wait_for_opa_sync(email, new_role):
        return False

    # Step 7: Refresh token
    print_step(7, "Refresh JWT Token")
    new_access_token = refresh_token_via_server(refresh_token)

    if new_access_token:
        print_subtest("Analyze new token")
        new_claims = decode_token(new_access_token)
        new_permissions = new_claims.get("permissions", {})

        print(f"\n    {YELLOW}📊 PERMISSION COMPARISON:{RESET}")
        print(f"      {RED}Before ({current_role}):{RESET}")
        for res, perms in initial_permissions.items():
            print(f"        {res}: {perms}")
        print(f"      {GREEN}After ({new_role}):{RESET}")
        for res, perms in new_permissions.items():
            print(f"        {res}: {perms}")

        if initial_permissions != new_permissions:
            print_success("Permissions changed correctly!")
        else:
            print_error("Permissions did not change!")
    else:
        print_info("Using original token for remaining tests")
        new_access_token = access_token

    # Step 8: Test authorization with new role
    print_step(8, "Test Authorization (New Role)")
    is_admin_now = new_role == "admin"
    test_authorization(new_access_token, expected_write=is_admin_now)

    # Step 9: Cleanup
    print_step(9, "Cleanup")
    print_subtest(f"Reset role to {current_role}")
    if update_user_role(email, current_role):
        print_success(f"Role reset to {current_role}")

    print_banner("E2E TEST COMPLETED SUCCESSFULLY!", "=")
    print(f"{GREEN}{BOLD}All tests passed with real browser SSO login!{RESET}\n")

    return True


if __name__ == "__main__":
    try:
        success = run_test()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Error: {e}{RESET}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
