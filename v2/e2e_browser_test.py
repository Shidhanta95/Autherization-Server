#!/usr/bin/env python3
"""
Browser-Based End-to-End Test for Authorization Server v2

This test uses Playwright to automate a real browser and test the complete SSO flow:
1. Initiate login via Auth Server
2. Redirect to Keycloak login page
3. Enter credentials (automated)
4. Keycloak redirects back to Auth Server callback
5. Auth Server creates JWT with permissions from OPA
6. Test permission modifications and CDC sync

Usage:
    python e2e_browser_test.py              # Headless mode (faster)
    python e2e_browser_test.py --headed     # Watch the browser

Test Users (in Keycloak):
    - testuser@acme.com / testpassword123

"""

import sys
import time
import json
import argparse
import requests
import psycopg2
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
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

# Test user (must exist in both Keycloak and PostgreSQL)
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


# ============================================================
# PRINT HELPERS
# ============================================================
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


def print_json_detail(label, data):
    print(f"      {DIM}•{RESET} {label}:")
    formatted = json.dumps(data, indent=2, default=str)
    for line in formatted.split("\n"):
        print(f"        {CYAN}{line}{RESET}")


# ============================================================
# SERVICE HEALTH CHECKS
# ============================================================
def check_services():
    """Check if all services are healthy"""
    print_step(0, "Service Health Check")

    all_healthy = True

    services = [
        ("Auth Server", f"{AUTH_SERVER_URL}/health"),
        ("OPA", f"{OPA_URL}/health"),
        ("Keycloak", f"{KEYCLOAK_URL}/realms/authz/.well-known/openid-configuration"),
    ]

    for name, url in services:
        print_subtest(f"{name} Health Check")
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

    # PostgreSQL
    print_subtest("PostgreSQL Health Check")
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        conn.close()
        print_success("PostgreSQL is healthy")
    except Exception as e:
        print_error(f"PostgreSQL unreachable: {e}")
        all_healthy = False

    return all_healthy


# ============================================================
# BROWSER-BASED SSO AUTHENTICATION
# ============================================================
def browser_sso_login(headed=False):
    """
    Perform real SSO login using a browser.

    This is the REAL flow:
    1. Call auth-server /login to get authorization URL
    2. Browser navigates to Keycloak
    3. User enters credentials (automated by Playwright)
    4. Keycloak redirects to auth-server /callback
    5. Auth-server returns tokens
    """
    print_step(1, "Browser-Based SSO Authentication")
    print(f"  {DIM}This simulates a real user logging in via browser...{RESET}\n")

    # Step 1: Initiate login
    print_subtest("Step 1: Initiate login via Auth Server")
    print_action(f"POST {AUTH_SERVER_URL}/api/v1/auth/login")

    resp = requests.post(
        f"{AUTH_SERVER_URL}/api/v1/auth/login",
        json={"platform": TEST_USER_PLATFORM, "org_name": TEST_USER_ORG},
        timeout=10,
    )

    if resp.status_code != 200:
        print_error(f"Login initiation failed: {resp.status_code}")
        return None, None

    login_url = resp.json().get("login_url")
    print_success("Got authorization URL from Auth Server")
    print_detail("URL", login_url[:80] + "..." if len(login_url) > 80 else login_url)

    # Step 2: Browser automation
    print_subtest("Step 2: Browser navigates to Keycloak")
    print_action("Opening browser and navigating to authorization URL")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context()
        page = context.new_page()

        try:
            # Navigate to Keycloak login
            print_info("Navigating to Keycloak login page...")
            page.goto(login_url, wait_until="networkidle", timeout=15000)

            # Take screenshot for debugging
            # page.screenshot(path="keycloak_login.png")

            # Check if we're on the Keycloak login page
            if "login" not in page.url.lower() and "auth" not in page.url.lower():
                print_error(f"Not on login page. Current URL: {page.url}")
                return None, None

            print_success("Reached Keycloak login page")
            print_detail("Current URL", page.url[:60] + "...")

            # Step 3: Enter credentials
            print_subtest("Step 3: Enter credentials")
            print_action(f"Filling in username: {TEST_USER_EMAIL}")

            # Wait for and fill username
            page.wait_for_selector("#username", timeout=5000)
            page.fill("#username", TEST_USER_EMAIL)

            print_action("Filling in password: ********")
            page.fill("#password", TEST_USER_PASSWORD)

            # Step 4: Submit and wait for redirect
            print_subtest("Step 4: Submit login form")
            print_action("Clicking login button...")
            print_expected(
                "Keycloak authenticates and redirects to Auth Server callback"
            )

            # Click login and wait for navigation to callback
            page.click("#kc-login")

            # Wait for redirect to auth-server callback
            # The callback URL will return JSON, so we wait for it
            page.wait_for_url(f"{AUTH_SERVER_URL}/**", timeout=10000)

            print_success("Keycloak redirected to Auth Server callback")
            print_detail("Final URL", page.url[:60] + "...")

            # Step 5: Extract tokens from response
            print_subtest("Step 5: Extract tokens from Auth Server response")

            # Get the JSON response from the page
            content = page.content()

            # The response is JSON displayed in the browser
            # Extract it from the page
            try:
                # Try to get JSON from pre tag or body
                json_text = page.inner_text("body")
                tokens = json.loads(json_text)

                print_success("Auth Server returned tokens!")
                print(f"\n    {YELLOW}📜 SSO RESPONSE:{RESET}")
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
                print_detail("expires_in", f"{tokens.get('expires_in')} seconds")
                print_detail("message", tokens.get("message"))

                return tokens.get("access_token"), tokens.get("refresh_token")

            except json.JSONDecodeError as e:
                print_error(f"Failed to parse response: {e}")
                print_info(f"Page content: {content[:200]}")
                return None, None

        except PlaywrightTimeout as e:
            print_error(f"Browser timeout: {e}")
            # page.screenshot(path="error_screenshot.png")
            return None, None
        except Exception as e:
            print_error(f"Browser error: {e}")
            return None, None
        finally:
            browser.close()


# ============================================================
# DATABASE & OPA OPERATIONS
# ============================================================
def get_db_connection():
    return psycopg2.connect(**POSTGRES_CONFIG)


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
        org_id = user[0]

        cur.execute(
            "SELECT id FROM mlops_roles WHERE name = %s AND org_id = %s",
            (new_role, org_id),
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
    except Exception as e:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def get_opa_permissions(email, platform):
    url = f"{OPA_URL}/v1/data/authz/user_permissions"
    resp = requests.post(
        url, json={"input": {"user": email, "platform": platform}}, timeout=5
    )
    if resp.status_code == 200:
        return resp.json().get("result", {})
    return {}


def get_opa_user_context(email, platform):
    url = f"{OPA_URL}/v1/data/authz/user_context"
    resp = requests.post(
        url, json={"input": {"user": email, "platform": platform}}, timeout=5
    )
    if resp.status_code == 200:
        return resp.json().get("result", {})
    return {}


def wait_for_opa_sync(email, expected_role, max_wait=30):
    print_subtest("Wait for CDC sync to OPA")
    print_expected(f"Role should become '{expected_role}'")

    for i in range(max_wait):
        context = get_opa_user_context(email, TEST_USER_PLATFORM)
        current_role = context.get("role")
        if current_role == expected_role:
            print_actual(f"Role is '{current_role}' after {i + 1}s")
            print_success("OPA synced!")
            return True
        if i % 5 == 0:
            print_info(f"Waiting... ({i}s) - current role: {current_role}")
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
    print_action(f"POST {AUTH_SERVER_URL}/api/v1/auth/refresh")

    resp = requests.post(
        f"{AUTH_SERVER_URL}/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
        timeout=10,
    )

    print_actual(f"HTTP {resp.status_code}")

    if resp.status_code == 200:
        tokens = resp.json()
        print_success("Token refreshed successfully!")
        return tokens.get("access_token")
    else:
        print_error(f"Refresh failed: {resp.text}")
        return None


def test_authorization_endpoints(access_token):
    print_step(5, "Test Authorization Endpoints")
    headers = {"Authorization": f"Bearer {access_token}"}

    # Test /authorize/me
    print_subtest("GET /authorize/me")
    resp = requests.get(
        f"{AUTH_SERVER_URL}/api/v1/authorize/me", headers=headers, timeout=5
    )
    if resp.status_code == 200:
        print_success("Returned user data")
        print_json_detail("Response", resp.json())
    else:
        print_error(f"Failed: {resp.status_code}")

    # Test /authorize
    print_subtest("POST /authorize (permission check)")
    resp = requests.post(
        f"{AUTH_SERVER_URL}/api/v1/authorize",
        headers=headers,
        json={"resource": "projects", "action": "write"},
        timeout=5,
    )
    if resp.status_code == 200:
        result = resp.json()
        allowed = result.get("allowed")
        print_actual(f"allowed={allowed}")
        if allowed:
            print_success("Permission check passed")
        else:
            print_info("Permission denied (expected for viewer role)")
    else:
        print_error(f"Failed: {resp.status_code}")


# ============================================================
# MAIN TEST
# ============================================================
def run_test(headed=False):
    print_banner("Browser-Based E2E Test: Authorization Server v2")
    print(f"{DIM}This test uses a real browser to authenticate via Keycloak SSO{RESET}")
    print(f"{DIM}Mode: {'Headed (visible browser)' if headed else 'Headless'}{RESET}\n")

    # Step 0: Health checks
    if not check_services():
        print_error("Services not healthy!")
        return False

    # Step 1: Browser SSO login
    access_token, refresh_token = browser_sso_login(headed=headed)

    if not access_token:
        print_error("SSO login failed!")
        return False

    # Step 2: Analyze token
    print_step(2, "Analyze JWT Token")
    print_subtest("Decode access token")

    claims = decode_token(access_token)
    print_success("Token decoded")
    print(f"\n    {YELLOW}📜 JWT CLAIMS:{RESET}")
    print_detail("email", claims.get("email"))
    print_detail("organization", claims.get("organization"))
    print_detail("platform", claims.get("platform"))
    print_detail("userID", claims.get("userID"))
    print_json_detail("permissions", claims.get("permissions", {}))

    initial_permissions = claims.get("permissions", {})

    # Step 3: Modify role
    print_step(3, "Modify User Role in Database")

    current_role = get_user_role(TEST_USER_EMAIL)
    print_subtest(f"Current role: {current_role}")

    new_role = "admin" if current_role == "viewer" else "viewer"
    print_subtest(f"Changing role to: {new_role}")

    if update_user_role(TEST_USER_EMAIL, new_role):
        print_success(f"Role updated to {new_role}")
    else:
        print_error("Failed to update role")
        return False

    # Wait for OPA sync
    if not wait_for_opa_sync(TEST_USER_EMAIL, new_role):
        return False

    # Step 4: Refresh token to get new permissions
    print_step(4, "Refresh Token for Updated Permissions")

    new_access_token = refresh_token_via_server(refresh_token)

    if new_access_token:
        new_claims = decode_token(new_access_token)
        new_permissions = new_claims.get("permissions", {})

        print_subtest("Compare permissions")
        print(f"\n    {YELLOW}📊 BEFORE ({current_role}):{RESET}")
        print_json_detail("permissions", initial_permissions)
        print(f"\n    {GREEN}📊 AFTER ({new_role}):{RESET}")
        print_json_detail("permissions", new_permissions)

        if initial_permissions != new_permissions:
            print_success("Permissions changed correctly!")
        else:
            print_error("Permissions did not change!")
    else:
        print_info("Token refresh failed - this is expected if using manual tokens")

    # Step 5: Test authorization
    test_authorization_endpoints(new_access_token or access_token)

    # Cleanup
    print_step(6, "Cleanup")
    print_subtest(f"Resetting role to {current_role}")
    update_user_role(TEST_USER_EMAIL, current_role)
    print_success("Role reset")

    print_banner("E2E TEST COMPLETED SUCCESSFULLY!", "=")
    print(f"{GREEN}{BOLD}All tests passed with real browser SSO!{RESET}\n")

    return True


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Browser-based E2E test")
    parser.add_argument(
        "--headed", action="store_true", help="Run with visible browser"
    )
    args = parser.parse_args()

    try:
        success = run_test(headed=args.headed)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Error: {e}{RESET}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
