"""
Configuration settings for the Auth Server.
Uses pydantic-settings for environment variable management.
"""

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # ============================================================
    # APPLICATION SETTINGS
    # ============================================================
    APP_NAME: str = "Auth Server"
    DEBUG: bool = False

    # ============================================================
    # JWT SETTINGS
    # ============================================================
    SECRET_KEY: str  # Required - used for signing JWTs
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ============================================================
    # OKTA / IDP SETTINGS
    # ============================================================
    OKTA_DOMAIN: str
    OKTA_ISSUER: str  # External URL (for browser redirects)
    OKTA_ISSUER_INTERNAL: str = ""  # Internal URL (for server-to-server, e.g., http://keycloak:8080/realms/authz)
    OKTA_CLIENT_ID: str
    OKTA_CLIENT_SECRET: str
    REDIRECT_URI: str

    # ============================================================
    # OPA SETTINGS
    # ============================================================
    OPA_URL: str = "http://opa:8181"

    # ============================================================
    # REDIS SETTINGS
    # ============================================================
    REDIS_URL: str = "redis://redis:6379"
    SESSION_TTL_SECONDS: int = 600  # 10 minutes for login state

    # ============================================================
    # PLATFORM SETTINGS
    # ============================================================
    PLATFORMS: List[str] = ["mlops", "analytics", "vision", "DC"]

    # ============================================================
    # HARDCODED LICENCE (TEMPORARY)
    # ============================================================
    # This will be replaced with actual licence service integration
    HARDCODED_LICENCE: dict = {
        "instanceid": "3f4e94a0-5bb8-4c59-ae36-1f17d7b2170d",
        "ip_address": "0.0.0.0",
        "organization": "default",
        "License": {
            "product_name": "platform",
            "product_version": "1.0",
            "activation_date": "2025-01-01T00:00:00",
            "expiration_date": "2030-12-31T00:00:00",
            "heartbeat": 4,
            "Features": [
                {"FeatureName": "maximum-users", "FeatureValue": 100},
                {"FeatureName": "maximum-business-unit", "FeatureValue": 50},
                {"FeatureName": "project", "FeatureValue": "true"},
                {"FeatureName": "pipeline", "FeatureValue": "true"},
                {"FeatureName": "experiment", "FeatureValue": "true"},
                {"FeatureName": "model-hub", "FeatureValue": "true"},
                {"FeatureName": "serving", "FeatureValue": "true"},
                {"FeatureName": "monitoring", "FeatureValue": "true"},
            ],
        },
        "Properties": {
            "project": True,
            "pipeline": True,
            "experiment": True,
            "model-hub": True,
            "serving": True,
            "monitoring": True,
        },
        "MaxUsers": 100,
        "MaxBUs": 50,
        "Permissions": {
            "project": False,
            "pipeline": False,
            "experiment": False,
            "model-hub": False,
            "serving": False,
            "monitoring": False,
        },
    }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


# Create a singleton instance
settings = Settings()
