"""
backend/core/config.py

Loads application settings from environment variables (or a .env file).
All secrets and connection strings must come through here — never hard-coded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env file when present (dev convenience); no-op in prod where vars are
# injected directly into the environment.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    odds_api_key: str
    model_artifact_path: str
    log_level: str
    discord_webhook_url: str  # empty string = disabled


def get_settings() -> Settings:
    """
    Build and return a Settings instance from environment variables.
    Raises RuntimeError for any required variable that is missing.
    """
    missing = []

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        missing.append("DATABASE_URL")

    odds_api_key = os.environ.get("ODDS_API_KEY", "")
    if not odds_api_key:
        missing.append("ODDS_API_KEY")

    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )

    return Settings(
        database_url=database_url,
        odds_api_key=odds_api_key,
        model_artifact_path=os.environ.get("MODEL_ARTIFACT_PATH", "models/nrfi_model.pkl"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", ""),
    )
