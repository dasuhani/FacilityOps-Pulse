"""
core/config.py
--------------
Centralised application configuration loaded from environment variables.

Usage:
    from core.config import settings

    db_url = settings.DATABASE_URL
    groq_key = settings.GROQ_API_KEY
"""

import os
import secrets
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root (the directory that contains this file's parent)
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
load_dotenv(dotenv_path=_env_file, override=False)

logger = logging.getLogger(__name__)


def _require(key: str) -> str:
    """Read a required env var; raise a clear error if missing."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"Copy .env.example to .env and fill in your values."
        )
    return value


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _get_bool(key: str, default: bool = True) -> bool:
    val = os.getenv(key, str(default)).strip().lower()
    return val in ("1", "true", "yes", "on")


class _Settings:
    """
    Single source of truth for all runtime configuration.
    Reads from environment variables once at import time.
    Never stores secrets in class source — values come from .env.
    """

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME: str = _get("APP_NAME", "FacilityOps Pulse")
    APP_ENV: str = _get("APP_ENV", "development")

    # Session secret — generated randomly if not set (safe for dev,
    # but sessions won't survive restarts without a fixed value in .env)
    SESSION_SECRET_KEY: str = _get("SESSION_SECRET_KEY") or secrets.token_hex(32)

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    # Full URL takes precedence over individual fields
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL") or None

    DB_HOST: str = _get("DB_HOST", "localhost")
    DB_PORT: int = int(_get("DB_PORT", "5432"))
    DB_NAME: str = _get("DB_NAME", "facilityops_pulse")
    DB_USER: str = _get("DB_USER", "")
    DB_PASSWORD: str = _get("DB_PASSWORD", "")

    # ------------------------------------------------------------------
    # Groq API
    # ------------------------------------------------------------------
    GROQ_API_KEY: str = _get("GROQ_API_KEY", "")
    GROQ_MODEL: str = _get("GROQ_MODEL", "llama-3.3-70b-versatile")

    # ------------------------------------------------------------------
    # Sentence Transformers
    # ------------------------------------------------------------------
    EMBEDDING_MODEL: str = _get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # ------------------------------------------------------------------
    # Feature flags
    # ------------------------------------------------------------------
    ENABLE_AI_FEATURES: bool = _get_bool("ENABLE_AI_FEATURES", True)
    ENABLE_SEMANTIC_SEARCH: bool = _get_bool("ENABLE_SEMANTIC_SEARCH", True)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    LOG_LEVEL: str = _get("LOG_LEVEL", "INFO").upper()
    LOG_FILE: str = _get("LOG_FILE", "logs/facilityops.log")

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV.lower() == "development"

    @property
    def ai_enabled(self) -> bool:
        """True only when the feature flag is on AND a key is present."""
        return self.ENABLE_AI_FEATURES and bool(self.GROQ_API_KEY)

    @property
    def semantic_search_enabled(self) -> bool:
        return self.ENABLE_SEMANTIC_SEARCH and self.ENABLE_AI_FEATURES

    def validate(self) -> list[str]:
        """
        Check for missing required settings.
        Returns a list of human-readable warning/error strings.
        Call this at application startup to surface config issues early.
        """
        issues: list[str] = []

        # Database: need either DATABASE_URL or all individual fields
        if not self.DATABASE_URL:
            if not self.DB_USER:
                issues.append("DB_USER is not set in .env")
            if not self.DB_PASSWORD:
                issues.append("DB_PASSWORD is not set in .env")
            if not self.DB_NAME:
                issues.append("DB_NAME is not set in .env")

        if not self.GROQ_API_KEY:
            issues.append(
                "GROQ_API_KEY is not set — AI features will be disabled. "
                "Get a free key at https://console.groq.com"
            )

        if self.SESSION_SECRET_KEY == "":
            issues.append(
                "SESSION_SECRET_KEY is not set — using a random key. "
                "Sessions will not persist across restarts."
            )

        return issues


# Module-level singleton — import this everywhere
settings = _Settings()
