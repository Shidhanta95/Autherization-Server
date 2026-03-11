# Testing Guide

Comprehensive guide for testing the User Management System.

## Test Structure

```
v2/auth-server/tests/
├── conftest.py           # Shared fixtures and configuration
├── test_auth.py          # Authentication endpoint tests
├── test_authorize.py     # Authorization endpoint tests
├── test_token_service.py # Token service unit tests
├── test_opa_service.py   # OPA service unit tests
└── test_integration.py   # End-to-end integration tests
```

## Running Tests

### Prerequisites

```bash
cd v2/auth-server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### Run All Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run specific test class
pytest tests/test_auth.py::TestLoginEndpoint

# Run specific test
pytest tests/test_auth.py::TestLoginEndpoint::test_login_success
```

### Run Tests with Docker

```bash
# Build test image
docker build -t auth-server-test -f Dockerfile .

# Run tests in container
docker run --rm auth-server-test pytest -v
```

## Test Categories

### 1. Unit Tests

Test individual components in isolation.

```bash
# Run unit tests only
pytest tests/test_token_service.py tests/test_opa_service.py -v
```

**Example: Token Service Test**

```python
def test_create_access_token(self, token_service):
    """Test access token creation"""
    token, expires = token_service.create_access_token(
        email="test@example.com",
        user_id="user-123",
        organization="testorg",
        platform="mlops",
        permissions={"projects": {"read": True}},
        org_admin=1,
    )

    # Verify token is valid JWT
    decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    assert decoded["email"] == "test@example.com"
    assert decoded["userID"] == "user-123"
    assert decoded["type"] == "access"
```

### 2. API Tests

Test API endpoints with mocked dependencies.

```bash
# Run API tests
pytest tests/test_auth.py tests/test_authorize.py -v
```

**Example: Login Endpoint Test**

```python
def test_login_success(self, client: TestClient, mock_session_service):
    """Test successful login initiation"""
    with patch("app.routers.auth.session_service", mock_session_service):
        response = client.post(
            "/api/v1/auth/login",
            json={"platform": "mlops", "org_name": "testorg"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "login_url" in data
```

### 3. Integration Tests

Test complete flows with mocked external services.

```bash
# Run integration tests
pytest tests/test_integration.py -v
```

**Example: Full Login Flow Test**

```python
def test_login_to_callback_flow(self, client, mock_session_service, mock_opa_service):
    """Test complete flow from login to callback"""
    # Step 1: Initiate login
    with patch("app.routers.auth.session_service", mock_session_service):
        login_response = client.post(
            "/api/v1/auth/login",
            json={"platform": "mlops", "org_name": "testorg"},
        )

    assert login_response.status_code == 200

    # Step 2: Simulate callback
    with patch("app.routers.auth.session_service", mock_session_service), \
         patch("app.routers.auth.opa_service", mock_opa_service), \
         patch("app.routers.auth.exchange_code_for_tokens") as mock_exchange:

        mock_exchange.return_value = {"id_token": "...", "access_token": "..."}
        # ... complete test
```

### 4. End-to-End Tests (E2E)

Test with real running services.

```bash
# Start services
cd v2
docker-compose up -d

# Wait for services to be ready
sleep 30

# Run E2E tests
pytest tests/test_e2e.py -v --e2e

# Stop services
docker-compose down
```

### 5. Interactive Browser E2E Test

A comprehensive E2E test that uses a real browser for SSO login with Keycloak.

```bash
cd v2

# Ensure services are running
docker-compose up -d

# Activate virtual environment
source venv/bin/activate

# Install Playwright if needed
pip install playwright
playwright install chromium

# Run the interactive test
python e2e_interactive_test.py
```

**What this test does:**

1. **Health Check** - Verifies all services are running (Auth Server, OPA, Keycloak, PostgreSQL)
2. **Browser Login** - Opens a real browser to Keycloak login page
3. **Manual Authentication** - You log in manually (native or federated IdP)
4. **Token Capture** - Captures JWT tokens from callback
5. **Token Analysis** - Decodes and displays token claims
6. **Authorization Test** - Tests permission checks with current role
7. **Role Change** - Modifies user role in PostgreSQL (viewer ↔ admin)
8. **CDC Sync** - Waits for Debezium to sync changes to OPA (~2-5s)
9. **Token Refresh** - Gets new token with updated permissions
10. **Permission Verification** - Confirms permissions changed correctly
11. **Cleanup** - Resets user role

**Test Users for Interactive Test:**

| Login Type | Credentials |
|------------|-------------|
| Native (Keycloak) | `testuser@acme.com` / `testpassword123` |
| Native (Keycloak) | `admin@acme.com` / `adminpassword123` |
| Federated (Okta) | Click "Login with Okta" button |

**Sample Output:**

```
======================================================================
            Interactive E2E Test: Authorization Server v2             
======================================================================

[STEP 0] Service Health Check
  ▶ TEST: Auth Server
    ✓ PASS: Auth Server is healthy
  ▶ TEST: OPA
    ✓ PASS: OPA is healthy
  ▶ TEST: Keycloak
    ✓ PASS: Keycloak is healthy
  ▶ TEST: PostgreSQL
    ✓ PASS: PostgreSQL is healthy

[STEP 1] Interactive Browser SSO Login
  ▶ TEST: Initiate login via Auth Server
    ✓ PASS: Got authorization URL
  ▶ TEST: Browser Login (Manual)
    ⏳ WAITING: Complete the login in the browser...
    ✓ PASS: Login completed!
    ✓ LOGIN SUCCESSFUL!
      • Email: testuser@acme.com
      • Organization: acme

[STEP 5] Modify User Role in Database
  ▶ TEST: Change role: viewer → admin
    ✓ PASS: Role updated to admin

[STEP 6] Wait for CDC Pipeline Sync
  ▶ TEST: Wait for CDC sync to OPA
    → Expecting role to become 'admin'
    ✓ PASS: OPA synced after 2s - role is now 'admin'

[STEP 7] Refresh JWT Token
    📊 PERMISSION COMPARISON:
      Before (viewer):
        projects: {'delete': False, 'read': True, 'write': False}
      After (admin):
        projects: {'delete': True, 'read': True, 'write': True}
    ✓ PASS: Permissions changed correctly!

======================================================================
                   E2E TEST COMPLETED SUCCESSFULLY!                   
======================================================================
```

### 6. Non-Interactive E2E Test

For CI/CD pipelines, use the test-login endpoint (bypasses SSO):

```bash
cd v2
source venv/bin/activate
python e2e_test.py
```

This test uses the `/api/v1/auth/test-login` endpoint which is only available when `DEBUG=true`.

## Test Fixtures

### Available Fixtures

| Fixture | Description |
|---------|-------------|
| `client` | Synchronous FastAPI test client |
| `async_client` | Asynchronous test client |
| `mock_user_context` | Mock user context from OPA |
| `mock_permissions` | Mock permissions from OPA |
| `valid_access_token` | Valid JWT access token |
| `expired_access_token` | Expired JWT for testing |
| `mock_opa_service` | Mocked OPA service |
| `mock_session_service` | Mocked Redis session service |

### Using Fixtures

```python
def test_authorize_with_valid_token(
    self, 
    client: TestClient, 
    valid_access_token, 
    mock_opa_service
):
    """Test authorization with valid token"""
    with patch("app.routers.authorize.opa_service", mock_opa_service):
        response = client.post(
            "/api/v1/authorize",
            json={"resource": "projects", "action": "write"},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )

    assert response.status_code == 200
```

## Mocking External Services

### Mocking OPA

```python
@pytest.fixture
def mock_opa_service():
    mock = AsyncMock()
    mock.check_user_exists.return_value = True
    mock.get_user_context.return_value = {
        "user_id": "test-user-id",
        "role": "admin",
        "organization": "testorg",
        "is_org_admin": 1,
    }
    mock.get_user_permissions.return_value = {
        "projects": {"read": True, "write": True, "delete": True},
    }
    return mock
```

### Mocking Redis

```python
@pytest.fixture
def mock_session_service():
    mock = AsyncMock()
    mock.store_login_state.return_value = True
    mock.get_login_state.return_value = {
        "platform": "mlops",
        "org_name": "testorg",
    }
    return mock
```

### Mocking Okta

```python
@pytest.fixture
def mock_okta_response():
    with patch("app.services.sso_service.exchange_code_for_tokens") as mock:
        mock.return_value = {
            "id_token": "mock-id-token",
            "access_token": "mock-access-token",
        }
        yield mock
```

## Coverage Report

### Generate Coverage Report

```bash
# Generate HTML coverage report
pytest --cov=app --cov-report=html

# Open report
open htmlcov/index.html  # Mac
xdg-open htmlcov/index.html  # Linux
```

### Coverage Targets

| Component | Target Coverage |
|-----------|-----------------|
| Routers | 90% |
| Services | 85% |
| Core | 95% |
| Overall | 85% |

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd v2/auth-server
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          cd v2/auth-server
          pytest --cov=app --cov-report=xml -v
        env:
          SECRET_KEY: test-secret-key
          OKTA_DOMAIN: test.okta.com
          OKTA_ISSUER: https://test.okta.com/oauth2/default
          OKTA_CLIENT_ID: test-client-id
          OKTA_CLIENT_SECRET: test-client-secret
          REDIRECT_URI: http://localhost:8000/api/v1/auth/callback
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## Writing New Tests

### Test Naming Convention

```python
# test_{component}.py

class Test{Endpoint/Service}:
    def test_{action}_{scenario}(self):
        """Test {description}"""
        pass

# Examples:
def test_login_success(self):
def test_login_invalid_platform(self):
def test_authorize_denied(self):
def test_refresh_expired_token(self):
```

### Test Template

```python
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


class TestMyFeature:
    """Tests for my feature"""

    def test_happy_path(self, client, valid_access_token):
        """Test normal successful operation"""
        response = client.post(
            "/api/v1/endpoint",
            json={"key": "value"},
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_validation_error(self, client, valid_access_token):
        """Test with invalid input"""
        response = client.post(
            "/api/v1/endpoint",
            json={},  # Missing required fields
            headers={"Authorization": f"Bearer {valid_access_token}"},
        )
        
        assert response.status_code == 422

    def test_unauthorized(self, client):
        """Test without authentication"""
        response = client.post(
            "/api/v1/endpoint",
            json={"key": "value"},
        )
        
        assert response.status_code == 401 or response.status_code == 403
```

## Debugging Tests

### Run with Debug Output

```bash
# Show print statements
pytest -s

# Show local variables on failure
pytest -l

# Drop into debugger on failure
pytest --pdb

# Verbose + show locals
pytest -vl
```

### Common Issues

**1. Import Errors**
```bash
# Ensure you're in the right directory
cd v2/auth-server
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

**2. Async Test Errors**
```python
# Mark async tests with pytest.mark.asyncio
@pytest.mark.asyncio
async def test_async_function(self):
    result = await some_async_function()
    assert result is not None
```

**3. Environment Variable Errors**
```python
# Set in conftest.py before imports
import os
os.environ["SECRET_KEY"] = "test-key"
```
