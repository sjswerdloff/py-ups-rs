"""Configuration handling for the pyupsrs server."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "info"
    database_uri: str = "sqlite:///ups.db"
    auth_enabled: bool = False


def get_config() -> Config:
    """Load configuration from environment variables."""
    return Config(
        host=os.getenv("PYUPSRS_HOST", "0.0.0.0"),
        port=int(os.getenv("PYUPSRS_PORT", "8000")),
        debug=os.getenv("PYUPSRS_DEBUG", "false").lower() == "true",
        log_level=os.getenv("PYUPSRS_LOG_LEVEL", "info"),
        database_uri=os.getenv("PYUPSRS_DATABASE_URI", "sqlite:///ups.db"),
        auth_enabled=os.getenv("PYUPSRS_AUTH_ENABLED", "false").lower() == "true",
    )
