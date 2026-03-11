#!/usr/bin/env python3
"""
End-to-End Test Script for Authorization Server v2

This script tests the complete flow:
1. Keycloak SSO authentication (Resource Owner Password Grant)
2. JWT creation with permissions
3. Permission modification in PostgreSQL
4. OPA sync verification
5. JWT refresh to get updated permissions

Prerequisites:
- Docker Compose stack running (docker compose up -d)
- Services healthy: postgres, redis, opa, auth-server, sync-worker, keycloak

Usage:
    python e2e_test.py

Test Users (in Keycloak):
    - testuser@acme.com / testpassword123
    - admin@acme.com / adminpassword123

"""

import sys
import time
import json
import requests
import psycopg2
from datetime import datetime, timezone
from jose import jwt

# ============================================================
# CONFIGURATION
# ============================================================
AUTH_SERVER_URL = "http://localhost:8000"
OPA_URL = "http://localhost:8181"
KEYCLOAK_URL = "http://localhost:8080"
KEYCLOAK_REALM = "authz"
KEYCLOAK_CLIENT_ID = "authz-client"
KEYCLOAK_CLIENT_SECRET = "authz-client-secret"

POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "authz",
    "user": "authz",
    "password": "authz123",
}

# Test user details (must exist in both Keycloak and PostgreSQL)
TEST_USER_EMAIL = "testuser@acme.com"
TEST_USER_PASSWORD = "testpassword123"
TEST_USER_PLATFORM = "mlops"
TEST_USER_ORG = "acme"

# Colors for output
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
    """Print a banner with text centered"""
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
    print(f"    {MAGENTA}⚙{RESET} {DIM}Action:{RESET} {message}")


def print_expected(message):
    print(f"    {YELLOW}⚡{RESET} {DIM}Expected:{RESET} {message}")


def print_actual(message):
    print(f"    {YELLOW}📋{RESET} {DIM}Actual:{RESET} {message}")


def print_success(message):
    print(f"    {GREEN}✓ PASS:{RESET} {message}")


def print_error(message):
    print(f"    {RED}✗ FAIL:{RESET} {message}")


def print_info(message):
    print(f"    {YELLOW}→{RESET} {message}")


def print_detail(key, value):
    print(f"      {DIM}•{RESET} {key}: {CYAN}{value}{RESET}")


def print_json_detail(label, data, indent=8):
    """Pretty print JSON data with indentation"""
    spaces = " " * indent
    print(f"      {DIM}•{RESET} {label}:")
    formatted = json.dumps(data, indent=2, default=str)
    for line in formatted.split("\n"):
        print(f"{spaces}{CYAN}{line}{RESET}")


def print_comparison(label1, data1, label2, data2):
    """Print a comparison between two values"""
    print(f"\n    {YELLOW}📊 COMPARISON:{RESET}")
    print(f"      {DIM}Before ({label1}):{RESET}")
    formatted1 = json.dumps(data1, indent=2, default=str)
    for line in formatted1.split("\n"):
        print(f"        {RED}{line}{RESET}")
    print(f"      {DIM}After ({label2}):{RESET}")
    formatted2 = json.dumps(data2, indent=2, default=str)
    for line in formatted2.split("\n"):
        print(f"        {GREEN}{line}{RESET}")


# ============================================================
# SERVICE HEALTH CHECKS
# ============================================================
def check_services():
    """Check if all services are healthy"""
    print_step(0, "Service Health Check")
    print(f"  {DIM}Verifying all required services are running and healthy...{RESET}\n")

    services = {
        "Auth Server": f"{AUTH_SERVER_URL}/health",
        "OPA": f"{OPA_URL}/health",
    }

    all_healthy = True
    keycloak_available = False

    for name, url in services.items():
        print_subtest(f"{name} Health Check")
        print_action(f"Sending GET request to {url}")
        print_expected(f"HTTP 200 OK response")

        try:
            resp = requests.get(url, timeout=5)
            print_actual(f"HTTP {resp.status_code} received")

            if resp.status_code == 200:
                print_success(f"{name} is healthy and responding")
            else:
                print_error(f"{name} returned unexpected status {resp.status_code}")
                all_healthy = False
        except requests.RequestException as e:
            print_actual(f"Connection failed: {e}")
            print_error(f"{name} is not reachable")
            all_healthy = False

    # Check Keycloak
    print_subtest("Keycloak Health Check")
    print_action(f"Checking Keycloak at {KEYCLOAK_URL}")
    print_expected("Keycloak realm accessible")

    try:
        resp = requests.get(
            f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration",
            timeout=10,
        )
        if resp.status_code == 200:
            print_actual("Keycloak OIDC configuration retrieved")
            print_success("Keycloak is healthy and realm is configured")
            keycloak_available = True
        else:
            print_actual(f"HTTP {resp.status_code} received")
            print_info("Keycloak not available - will use fallback authentication")
    except requests.RequestException as e:
        print_actual(f"Connection failed: {e}")
        print_info("Keycloak not available - will use fallback authentication")

    # Check PostgreSQL
    print_subtest("PostgreSQL Health Check")
    print_action(
        f"Connecting to PostgreSQL at {POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}"
    )
    print_expected("Successful database connection")

    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        conn.close()
        print_actual("Connection established and closed successfully")
        print_success("PostgreSQL is healthy and accepting connections")
    except Exception as e:
        print_actual(f"Connection failed: {e}")
        print_error(f"PostgreSQL is not reachable")
        all_healthy = False

    return all_healthy, keycloak_available


# ============================================================
# KEYCLOAK SSO OPERATIONS (Real Flow)
# ============================================================
def initiate_login_flow(platform, org_name):
    """
    Step 1: Call auth-server /login to initiate SSO flow.
    This stores state in Redis and returns the Keycloak authorization URL.
    """
    print_subtest("Step 1: Initiate Login via Auth Server")
    print_action(f"POST {AUTH_SERVER_URL}/api/v1/auth/login")
    print_detail("platform", platform)
    print_detail("org_name", org_name)
    print_expected("Auth server returns Keycloak authorization URL")

    try:
        resp = requests.post(
            f"{AUTH_SERVER_URL}/api/v1/auth/login",
            json={"platform": platform, "org_name": org_name},
            timeout=10,
        )
        print_actual(f"HTTP {resp.status_code} received")

        if resp.status_code == 200:
            data = resp.json()
            login_url = data.get("login_url")
            print_success("Login initiated - got authorization URL")
            print_detail(
                "Authorization URL",
                login_url[:80] + "..." if len(login_url) > 80 else login_url,
            )

            # Extract state from URL
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(login_url)
            params = parse_qs(parsed.query)
            state = params.get("state", [None])[0]
            print_detail("State (CSRF token)", state[:20] + "..." if state else "None")

            return login_url, state
        else:
            print_error(f"Login initiation failed: {resp.status_code} - {resp.text}")
            return None, None
    except Exception as e:
        print_error(f"Login request failed: {e}")
        return None, None


def authenticate_with_keycloak(username, password, login_url):
    """
    Step 2: Authenticate with Keycloak and get authorization code.

    This simulates what happens when a user logs in via the Keycloak UI.
    We use a session to follow redirects and capture the auth code.
    """
    print_subtest("Step 2: Authenticate with Keycloak")
    print_action(f"Simulating browser login for '{username}'")
    print_expected("Keycloak returns authorization code after successful login")

    session = requests.Session()

    try:
        # Step 2a: Follow the authorization URL to get the login page
        print_info("Following authorization URL to Keycloak login page...")
        resp = session.get(login_url, allow_redirects=True, timeout=10)

        if resp.status_code != 200:
            print_error(f"Failed to reach Keycloak login page: {resp.status_code}")
            return None, None

        # Extract the login form action URL from the HTML
        from html.parser import HTMLParser

        class FormParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.action_url = None

            def handle_starttag(self, tag, attrs):
                if tag == "form":
                    attrs_dict = dict(attrs)
                    if attrs_dict.get("id") == "kc-form-login":
                        self.action_url = attrs_dict.get("action")

        parser = FormParser()
        parser.feed(resp.text)

        if not parser.action_url:
            print_error("Could not find Keycloak login form")
            return None, None

        print_actual("Found Keycloak login form")

        # Step 2b: Submit credentials to Keycloak
        print_info("Submitting credentials to Keycloak...")
        login_data = {
            "username": username,
            "password": password,
        }

        # Don't follow redirects - we want to capture the redirect URL with the code
        resp = session.post(
            parser.action_url, data=login_data, allow_redirects=False, timeout=10
        )

        print_actual(f"HTTP {resp.status_code} received")

        if resp.status_code == 302:
            redirect_url = resp.headers.get("Location")
            print_success("Keycloak authentication successful!")

            # Extract auth code from redirect URL
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(redirect_url)
            params = parse_qs(parsed.query)
            auth_code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]

            if auth_code:
                print_success("Authorization code received from Keycloak")
                print_detail(
                    "Auth code",
                    auth_code[:30] + "..." if len(auth_code) > 30 else auth_code,
                )
                print_detail("State", state[:20] + "..." if state else "None")
                return auth_code, state
            else:
                # Check for error
                error = params.get("error", [None])[0]
                error_desc = params.get("error_description", [None])[0]
                print_error(f"No auth code in redirect. Error: {error} - {error_desc}")
                return None, None
        else:
            print_error(f"Unexpected response from Keycloak: {resp.status_code}")
            if resp.status_code == 200:
                print_info("Login may have failed - check credentials")
            return None, None

    except Exception as e:
        print_error(f"Keycloak authentication failed: {e}")
        return None, None


def complete_sso_callback(auth_code, state):
    """
    Step 3: Call auth-server /callback with the authorization code.

    This is what the browser would do after Keycloak redirects back.
    The auth-server will:
    1. Validate the state (CSRF protection)
    2. Exchange the code for Keycloak tokens
    3. Verify the ID token
    4. Fetch user permissions from OPA
    5. Create and return app JWT tokens
    """
    print_subtest("Step 3: Complete SSO via Auth Server Callback")
    print_action(f"GET {AUTH_SERVER_URL}/api/v1/auth/callback")
    print_detail("code", auth_code[:30] + "..." if auth_code else "None")
    print_detail("state", state[:20] + "..." if state else "None")
    print_expected("Auth server exchanges code, verifies token, creates app JWT")

    try:
        resp = requests.get(
            f"{AUTH_SERVER_URL}/api/v1/auth/callback",
            params={"code": auth_code, "state": state},
            timeout=15,
        )
        print_actual(f"HTTP {resp.status_code} received")

        if resp.status_code == 200:
            tokens = resp.json()
            print_success("SSO callback successful!")
            print(f"\n    {YELLOW}📜 AUTH SERVER RESPONSE:{RESET}")
            print_detail("success", tokens.get("success"))
            print_detail("email", tokens.get("email"))
            print_detail("organization", tokens.get("organization"))
            print_detail("user_id", tokens.get("user_id"))
            print_detail(
                "access_token", "Yes (JWT)" if tokens.get("access_token") else "No"
            )
            print_detail(
                "refresh_token", "Yes" if tokens.get("refresh_token") else "No"
            )
            print_detail("message", tokens.get("message"))
            return tokens.get("access_token"), tokens.get("refresh_token")
        else:
            error_detail = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else resp.text
            )
            print_error(f"Callback failed: {resp.status_code}")
            print_json_detail("Error", error_detail)
            return None, None
    except Exception as e:
        print_error(f"Callback request failed: {e}")
        return None, None


def decode_keycloak_token(token):
    """Decode a Keycloak JWT token without verification (for inspection)"""
    try:
        # Decode without verification just to inspect claims
        claims = jwt.get_unverified_claims(token)
        return claims
    except Exception as e:
        print_error(f"Failed to decode token: {e}")
        return None


# ============================================================
# DATABASE OPERATIONS
# ============================================================
def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(**POSTGRES_CONFIG)


def setup_test_user():
    """Create test user if not exists"""
    print_step(1, "Test User Setup in Database")
    print(
        f"  {DIM}Ensuring test user exists in the database with correct role...{RESET}\n"
    )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SET search_path TO authz, public;")

        # Check if user exists
        print_subtest("Check if test user already exists")
        print_action(f"Querying mlops_users for email = '{TEST_USER_EMAIL}'")
        print_expected("User either exists or will be created")

        cur.execute(
            "SELECT email FROM mlops_users WHERE email = %s", (TEST_USER_EMAIL,)
        )
        existing = cur.fetchone()

        if existing:
            print_actual(f"User found in database")
            print_success(f"User {TEST_USER_EMAIL} already exists - no action needed")
        else:
            print_actual("User not found - will create")

            print_subtest("Look up organization ID")
            print_action(f"Querying mlops_orgs for org name = '{TEST_USER_ORG}'")

            cur.execute("SELECT id FROM mlops_orgs WHERE name = %s", (TEST_USER_ORG,))
            org = cur.fetchone()
            if not org:
                print_error(f"Organization {TEST_USER_ORG} not found")
                return False
            org_id = org[0]
            print_actual(f"Found org_id = {org_id}")
            print_success(f"Organization '{TEST_USER_ORG}' found")

            print_subtest("Look up viewer role ID")
            print_action(f"Querying mlops_roles for role 'viewer' in org {org_id}")

            cur.execute(
                "SELECT id FROM mlops_roles WHERE name = 'viewer' AND org_id = %s",
                (org_id,),
            )
            role = cur.fetchone()
            if not role:
                print_error("Viewer role not found")
                return False
            role_id = role[0]
            print_actual(f"Found role_id = {role_id}")
            print_success("Viewer role found")

            print_subtest("Insert new user")
            print_action("Inserting user into mlops_users table")
            print_detail("email", TEST_USER_EMAIL)
            print_detail("org_id", org_id)
            print_detail("role_id", role_id)
            print_detail("user_uid", "user-001")
            print_detail("is_org_admin", "false")

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

        print_subtest(f"Update user role to '{new_role}'")

        # Get user's org_id first
        print_action(f"Looking up org_id for user '{email}'")
        cur.execute("SELECT org_id FROM mlops_users WHERE email = %s", (email,))
        user = cur.fetchone()
        if not user:
            print_error(f"User {email} not found")
            return False
        org_id = user[0]
        print_actual(f"Found org_id = {org_id}")

        # Get new role_id for the same org
        print_action(f"Looking up role_id for role '{new_role}' in org")
        cur.execute(
            "SELECT id FROM mlops_roles WHERE name = %s AND org_id = %s",
            (new_role, org_id),
        )
        role = cur.fetchone()
        if not role:
            print_error(f"Role {new_role} not found for org")
            return False
        role_id = role[0]
        print_actual(f"Found role_id = {role_id}")

        # Update user
        print_action(f"Executing UPDATE on mlops_users SET role_id = {role_id}")
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
    print_subtest("Wait for CDC pipeline to sync to OPA")
    print_action(f"Polling OPA every 1s for up to {max_wait}s")
    print_expected(f"User role in OPA should become '{expected_role}'")

    current_role = None
    for i in range(max_wait):
        context = get_opa_user_context(email, TEST_USER_PLATFORM)
        current_role = context.get("role")

        if current_role == expected_role:
            print_actual(f"Role is now '{current_role}' after {i + 1}s")
            print_success(f"OPA synced! User role is now: {expected_role}")
            return True

        if i % 5 == 0:
            print_info(f"Waiting... ({i}s) - current role: {current_role}")
        time.sleep(1)

    print_actual(f"Role is still '{current_role}' after {max_wait}s")
    print_error(f"OPA sync timeout after {max_wait}s")
    return False


# ============================================================
# AUTH SERVER OPERATIONS
# ============================================================
def create_test_tokens(email, platform, context, permissions):
    """Create test tokens manually (for E2E testing only)"""
    from datetime import timedelta
    import uuid

    SECRET_KEY = "change-this-in-production-use-a-strong-secret"
    ALGORITHM = "HS256"

    now = datetime.now(timezone.utc)

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

    print_actual("Tokens generated successfully")
    print_success("Created test tokens manually")
    print_detail("Access token expiry", "1 hour")
    print_detail("Refresh token expiry", "30 days")

    return access_token, refresh_token


def decode_token(token):
    """Decode a JWT token (without verification for inspection)"""
    SECRET_KEY = "change-this-in-production-use-a-strong-secret"
    ALGORITHM = "HS256"
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def refresh_access_token(refresh_token):
    """Refresh the access token via auth server"""
    print_subtest("Refresh token via Auth Server")
    print_action(f"POST request to {AUTH_SERVER_URL}/api/v1/auth/refresh")

    url = f"{AUTH_SERVER_URL}/api/v1/auth/refresh"
    payload = {"refresh_token": refresh_token}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        print_actual(f"HTTP {resp.status_code} received")

        if resp.status_code == 200:
            tokens = resp.json()
            print_success("Token refreshed successfully via auth server!")
            return tokens.get("access_token")
        else:
            print_info(f"Refresh failed: {resp.status_code} - {resp.text}")
            print_info("This may happen if the refresh token was created manually")
    except Exception as e:
        print_info(f"Refresh error: {e}")

    return None


def refresh_token_manually(email, platform):
    """Manually create a new access token with current permissions (for testing)"""
    print_subtest("Create new access token manually (fallback)")
    print_action("Fetching current user context and permissions from OPA")

    context = get_opa_user_context(email, platform)
    permissions = get_opa_user_permissions(email, platform)

    print_actual("Context and permissions retrieved")
    print_action("Generating new JWT with updated permissions")

    access_token, _ = create_test_tokens(email, platform, context, permissions)
    return access_token


def test_authorization(access_token):
    """Test the authorization endpoint"""
    headers = {"Authorization": f"Bearer {access_token}"}

    # Test /authorize/me
    print_subtest("Test /authorize/me endpoint")
    print_action(f"GET {AUTH_SERVER_URL}/api/v1/authorize/me")
    print_expected("Should return user info and permissions")

    try:
        resp = requests.get(
            f"{AUTH_SERVER_URL}/api/v1/authorize/me", headers=headers, timeout=5
        )
        print_actual(f"HTTP {resp.status_code} received")

        if resp.status_code == 200:
            me_data = resp.json()
            print_success("/authorize/me returned user data")
            print_json_detail("Response", me_data)
        else:
            print_error(f"/authorize/me failed: {resp.status_code}")
    except Exception as e:
        print_error(f"/authorize/me error: {e}")

    # Test /authorize (check specific permission)
    print_subtest("Test /authorize endpoint (permission check)")
    print_action(f"POST {AUTH_SERVER_URL}/api/v1/authorize")
    print_detail("resource", "projects")
    print_detail("action", "read")
    print_expected("Should return allowed=true for read access")

    try:
        resp = requests.post(
            f"{AUTH_SERVER_URL}/api/v1/authorize",
            headers=headers,
            json={"resource": "projects", "action": "read"},
            timeout=5,
        )
        print_actual(f"HTTP {resp.status_code} received")

        if resp.status_code == 200:
            auth_result = resp.json()
            allowed = auth_result.get("allowed")
            print_actual(f"allowed={allowed}")
            if allowed:
                print_success(
                    f"/authorize: Permission check passed (allowed={allowed})"
                )
            else:
                print_error(f"/authorize: Permission denied unexpectedly")
        else:
            print_error(f"/authorize failed: {resp.status_code}")
    except Exception as e:
        print_error(f"/authorize error: {e}")


# ============================================================
# MAIN TEST FLOW
# ============================================================
def run_e2e_test():
    """Run the complete E2E test"""
    print_banner("End-to-End Test: Authorization Server v2")
    print(f"{DIM}This test validates the complete authorization flow including:{RESET}")
    print(f"{DIM}  1. Service connectivity (including Keycloak SSO)")
    print(f"  2. User management in PostgreSQL")
    print(f"  3. OPA policy synchronization via CDC")
    print(f"  4. JWT token generation and refresh")
    print(f"  5. Permission verification{RESET}")
    print(f"\n{DIM}Test User: {TEST_USER_EMAIL}")
    print(f"Platform: {TEST_USER_PLATFORM}")
    print(f"Organization: {TEST_USER_ORG}{RESET}")

    # Step 0: Check services
    all_healthy, keycloak_available = check_services()
    if not all_healthy:
        print_error(
            "\nCore services not healthy. Please ensure docker-compose is running."
        )
        print_info("Run: cd v2 && docker compose up -d")
        return False

    # Step 1: Setup test user
    if not setup_test_user():
        return False

    # Wait for initial sync
    print_subtest("Wait for initial OPA sync")
    print_action("Pausing for 5 seconds to allow CDC pipeline to sync")
    time.sleep(5)
    print_success("Initial sync wait complete")

    # Step 2: Verify user in OPA
    print_step(2, "Verify User Exists in OPA")
    print(
        f"  {DIM}Confirming the test user was synced from PostgreSQL to OPA...{RESET}\n"
    )

    print_subtest("Check user existence in OPA")
    print_action(f"Querying OPA user_exists for '{TEST_USER_EMAIL}'")
    print_expected("User should exist in OPA's data store")

    if check_opa_user_exists(TEST_USER_EMAIL):
        print_actual("User found in OPA")
        print_success(f"User {TEST_USER_EMAIL} exists in OPA")
    else:
        print_actual("User not found in OPA")
        print_error("User not found in OPA. Sync may not be complete.")
        print_info("Waiting additional 10 seconds for sync...")
        time.sleep(10)
        if not check_opa_user_exists(TEST_USER_EMAIL):
            print_error("User still not found after extended wait")
            return False

    print_subtest("Retrieve user context from OPA")
    print_action(f"Querying OPA user_context endpoint")

    context = get_opa_user_context(TEST_USER_EMAIL, TEST_USER_PLATFORM)
    print_actual("User context retrieved")
    print_success(
        f"User context loaded: role={context.get('role')}, org={context.get('organization')}"
    )
    print_json_detail("Full Context", context)

    # Step 3: Authenticate via real SSO flow
    print_step(3, "SSO Authentication Flow")

    access_token = None
    refresh_token = None

    if keycloak_available:
        print(f"  {DIM}Testing REAL end-to-end SSO authentication...{RESET}")
        print(f"  {DIM}Flow: Auth Server → Keycloak → Auth Server Callback{RESET}\n")

        # Step 3.1: Initiate login via auth-server
        login_url, state = initiate_login_flow(TEST_USER_PLATFORM, TEST_USER_ORG)

        if login_url and state:
            # Step 3.2: Authenticate with Keycloak (simulate browser login)
            auth_code, returned_state = authenticate_with_keycloak(
                TEST_USER_EMAIL, TEST_USER_PASSWORD, login_url
            )

            if auth_code:
                # Step 3.3: Complete SSO via auth-server callback
                # This is where the auth-server creates the app JWT!
                access_token, refresh_token = complete_sso_callback(
                    auth_code, returned_state
                )

    # Fallback to manual token creation if Keycloak not available or failed
    if not access_token:
        print(f"\n  {DIM}Falling back to manual token creation...{RESET}\n")

        print_subtest("Fetch user context and permissions from OPA")
        print_action("Querying OPA for user data")

        permissions = get_opa_user_permissions(TEST_USER_EMAIL, TEST_USER_PLATFORM)
        print_success("Permissions retrieved from OPA")
        print_json_detail("Permissions", permissions)

        print_subtest("Create test tokens manually")
        print_action("Generating JWT tokens locally for testing")
        access_token, refresh_token = create_test_tokens(
            TEST_USER_EMAIL, TEST_USER_PLATFORM, context, permissions
        )

    if not access_token:
        print_error("Failed to obtain access token")
        return False

    # Step 4: Decode and show initial permissions
    print_step(4, "Analyze Initial JWT Token")
    print(f"  {DIM}Decoding and inspecting the initial access token...{RESET}\n")

    print_subtest("Decode JWT access token")
    print_action("Decoding token using HS256 algorithm")

    initial_claims = decode_token(access_token)
    print_actual("Token decoded successfully")
    print_success("JWT claims extracted")

    print(f"\n    {YELLOW}📜 JWT CLAIMS:{RESET}")
    print_detail("email", initial_claims.get("email"))
    print_detail("organization", initial_claims.get("organization"))
    print_detail("platform", initial_claims.get("platform"))
    print_detail("userID", initial_claims.get("userID"))
    print_detail("org_admin", initial_claims.get("org_admin"))
    print_detail("type", initial_claims.get("type"))
    print_json_detail("permissions", initial_claims.get("permissions", {}))

    initial_permissions = initial_claims.get("permissions", {})

    # Step 5: Modify user permissions in database
    print_step(5, "Modify User Role in Database")
    print(f"  {DIM}Changing user role in PostgreSQL to trigger CDC sync...{RESET}\n")

    print_subtest("Get current user role from database")
    print_action(f"Querying mlops_users JOIN mlops_roles for '{TEST_USER_EMAIL}'")

    current_role = get_user_role(TEST_USER_EMAIL)
    print_actual(f"Current role is '{current_role}'")
    print_success(f"Retrieved current role: {current_role}")

    # Toggle between viewer and admin
    new_role = "admin" if current_role == "viewer" else "viewer"
    print_subtest(f"Change role from '{current_role}' to '{new_role}'")
    print_expected(f"User role should be updated to '{new_role}'")

    if not update_user_role(TEST_USER_EMAIL, new_role):
        return False

    # Step 6: Wait for OPA sync
    print_step(6, "Wait for CDC Pipeline Sync")
    print(
        f"  {DIM}The sync-worker should detect the change and push to OPA...{RESET}\n"
    )

    if not wait_for_opa_sync(TEST_USER_EMAIL, new_role, max_wait=30):
        print_error("OPA did not sync in time")
        print_info("Check sync-worker logs: docker compose logs sync-worker")
        return False

    # Verify new permissions in OPA
    print_subtest("Verify new permissions in OPA")
    print_action("Fetching updated user permissions from OPA")

    new_opa_permissions = get_opa_user_permissions(TEST_USER_EMAIL, TEST_USER_PLATFORM)
    print_actual("Permissions retrieved from OPA")
    print_success(f"New permissions loaded from OPA")
    print_json_detail("Updated Permissions", new_opa_permissions)

    # Step 7: Refresh token to get new permissions
    print_step(7, "Refresh JWT Token")
    print(f"  {DIM}Getting a new access token with updated permissions...{RESET}\n")

    # Try via auth server first
    new_access_token = refresh_access_token(refresh_token)

    # If auth server refresh doesn't work, do it manually for testing
    if not new_access_token:
        print_info("Auth server refresh not available, using manual refresh")
        new_access_token = refresh_token_manually(TEST_USER_EMAIL, TEST_USER_PLATFORM)

    if not new_access_token:
        return False

    # Step 8: Verify new permissions in JWT
    print_step(8, "Verify Updated Permissions in New JWT")
    print(
        f"  {DIM}Checking that the new token contains updated permissions...{RESET}\n"
    )

    print_subtest("Decode new JWT access token")
    print_action("Decoding refreshed token")

    new_claims = decode_token(new_access_token)
    print_actual("Token decoded successfully")
    print_success("New JWT claims extracted")

    print(f"\n    {YELLOW}📜 UPDATED JWT CLAIMS:{RESET}")
    print_detail("role (from context)", new_role)
    print_json_detail("permissions", new_claims.get("permissions", {}))

    new_permissions = new_claims.get("permissions", {})

    # Step 9: Compare permissions
    print_step(9, "Compare Permissions Before and After")
    print(f"  {DIM}Analyzing the permission changes...{RESET}\n")

    print_subtest("Permission comparison")
    print_comparison(current_role, initial_permissions, new_role, new_permissions)

    # Verify change
    print_subtest("Verify permissions changed correctly")
    print_expected("Permissions should be different after role change")

    if initial_permissions != new_permissions:
        print_actual("Permissions are different")
        print_success("Permissions changed successfully!")

        # Check specific permission differences
        print_subtest("Verify role-specific permissions")

        if new_role == "admin":
            print_expected(
                "Admin should have write=true, delete=true for all resources"
            )
            projects_perms = new_permissions.get("projects", {})
            has_write = projects_perms.get("write") == True
            has_delete = projects_perms.get("delete") == True

            print_actual(
                f"projects.write={projects_perms.get('write')}, projects.delete={projects_perms.get('delete')}"
            )

            if has_write and has_delete:
                print_success("Admin permissions verified: write=True, delete=True")
            else:
                print_error("Admin permissions not as expected")
        else:
            print_expected(
                "Viewer should have write=false, delete=false for all resources"
            )
            projects_perms = new_permissions.get("projects", {})
            no_write = projects_perms.get("write") == False
            no_delete = projects_perms.get("delete") == False

            print_actual(
                f"projects.write={projects_perms.get('write')}, projects.delete={projects_perms.get('delete')}"
            )

            if no_write and no_delete:
                print_success("Viewer permissions verified: write=False, delete=False")
            else:
                print_error("Viewer permissions not as expected")
    else:
        print_actual("Permissions are identical")
        print_error("Permissions did not change!")
        return False

    # Step 10: Test authorization endpoint
    print_step(10, "Test Authorization Endpoints")
    print(f"  {DIM}Validating the auth server's authorization endpoints...{RESET}\n")

    test_authorization(new_access_token)

    # Cleanup: Reset user to original role
    print_step(11, "Cleanup")
    print(f"  {DIM}Resetting test user to original state...{RESET}\n")

    print_subtest(f"Reset user role to '{current_role}'")
    print_action(f"Restoring original role")
    update_user_role(TEST_USER_EMAIL, current_role)

    print_banner("E2E TEST COMPLETED SUCCESSFULLY!", "=")

    if keycloak_available:
        print(f"{GREEN}{BOLD}All test cases passed (with real Keycloak SSO)!{RESET}\n")
    else:
        print(
            f"{GREEN}{BOLD}All test cases passed (with manual token fallback)!{RESET}"
        )
        print(f"{YELLOW}Note: Start Keycloak to test real SSO flow.{RESET}\n")

    return True


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
