"""
SSO Service - Handles Single Sign-On flow with identity providers.

Supports:
- Okta OAuth 2.0 / OIDC flow
- Authorization URL generation
- Token exchange
- ID token verification
"""

import uuid
from urllib.parse import urlencode
from typing import Tuple, Optional, Dict, Any

import httpx
from jose import jwt, JWTError

from app.core.config import settings


async def get_sso_config_for_org(org_name: str) -> Optional[Dict[str, str]]:
    """
    Get SSO configuration for an organization.

    In a full implementation, this would query a database to get
    organization-specific IdP settings. For now, we use global settings.

    Args:
        org_name: The organization name

    Returns:
        Dict with client_id and issuer, or None if not configured
    """
    # TODO: Query database for org-specific SSO config
    # For now, return global Okta settings
    return {
        "client_id": settings.OKTA_CLIENT_ID,
        "issuer": settings.OKTA_ISSUER,
    }


def create_authorization_url(
    client_id: str,
    issuer: str,
    state: str,
) -> Tuple[str, str]:
    """
    Generate the OAuth 2.0 authorization URL for the IdP.

    Args:
        client_id: The OAuth client ID
        issuer: The IdP issuer URL
        state: The state parameter for CSRF protection

    Returns:
        Tuple of (authorization_url, nonce)
    """
    nonce = str(uuid.uuid4())

    # Detect IdP type based on issuer URL
    # Keycloak: http://localhost:8080/realms/authz
    # Okta: https://dev-xxxxx.okta.com/oauth2/default
    if "/realms/" in issuer:
        # Keycloak format
        auth_endpoint = f"{issuer}/protocol/openid-connect/auth"
    else:
        # Okta format
        auth_endpoint = f"{issuer}/v1/authorize"

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": settings.REDIRECT_URI,
        "state": state,
        "nonce": nonce,
    }

    return f"{auth_endpoint}?{urlencode(params)}", nonce


async def exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    """
    Exchange an authorization code for tokens.

    Args:
        code: The authorization code from the IdP callback

    Returns:
        Dict containing access_token, id_token, etc.

    Raises:
        httpx.HTTPStatusError: If the token exchange fails
    """
    # Use internal URL for server-to-server communication (Docker networking)
    issuer = settings.OKTA_ISSUER_INTERNAL or settings.OKTA_ISSUER

    # Detect IdP type based on issuer URL
    if "/realms/" in issuer:
        # Keycloak format
        token_endpoint = f"{issuer}/protocol/openid-connect/token"
    else:
        # Okta format
        token_endpoint = f"{issuer}/v1/token"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.REDIRECT_URI,
    }

    async with httpx.AsyncClient() as client:
        auth = (settings.OKTA_CLIENT_ID, settings.OKTA_CLIENT_SECRET)
        response = await client.post(
            token_endpoint,
            headers=headers,
            data=data,
            auth=auth,
            timeout=30.0,
        )

    response.raise_for_status()
    return response.json()


async def verify_id_token(id_token: str, access_token: str) -> Optional[Dict[str, Any]]:
    """
    Verify an ID token from the IdP.

    Args:
        id_token: The ID token to verify
        access_token: The access token (used for at_hash validation)

    Returns:
        The verified token claims, or None if verification fails
    """
    # Use internal URL for server-to-server communication (Docker networking)
    issuer_internal = settings.OKTA_ISSUER_INTERNAL or settings.OKTA_ISSUER
    issuer_external = (
        settings.OKTA_ISSUER
    )  # For token validation (issuer claim uses external URL)

    # Detect IdP type based on issuer URL
    if "/realms/" in issuer_internal:
        # Keycloak format
        jwks_endpoint = f"{issuer_internal}/protocol/openid-connect/certs"
    else:
        # Okta format
        jwks_endpoint = f"{issuer_internal}/v1/keys"

    async with httpx.AsyncClient() as client:
        response = await client.get(jwks_endpoint, timeout=10.0)
        response.raise_for_status()
        jwks = response.json()

    try:
        # Get the key ID from the token header
        unverified_header = jwt.get_unverified_header(id_token)

        # Find the matching public key
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
                break

        if not rsa_key:
            print("[SSO] Public key not found in JWKS")
            return None

        # Verify and decode the token
        # Note: issuer in token will be external URL, so we validate against that
        claims = jwt.decode(
            id_token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.OKTA_CLIENT_ID,
            issuer=issuer_external,
            access_token=access_token,
        )

        return claims

    except JWTError as e:
        print(f"[SSO] Token verification failed: {e}")
        return None
