"""Configuration handling for the pyupsrs server."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration."""

    host: str = "0.0.0.0"
    port: int = 8104
    debug: bool = False
    log_level: str = "info"
    database_uri: str = "sqlite:///ups.db"
    auth_enabled: bool = True
    ws_host: str = "0.0.0.0"
    ws_port: int = 10465


def get_config() -> Config:
    """Load configuration from environment variables."""
    return Config(
        host=os.getenv("PYUPSRS_HOST", "0.0.0.0"),
        port=int(os.getenv("PYUPSRS_PORT", "8104")),
        debug=os.getenv("PYUPSRS_DEBUG", "false").lower() == "true",
        log_level=os.getenv("PYUPSRS_LOG_LEVEL", "info"),
        database_uri=os.getenv("PYUPSRS_DATABASE_URI", "sqlite:///ups.db"),
        auth_enabled=os.getenv("PYUPSRS_AUTH_ENABLED", "true").lower() == "true",
        ws_host=os.getenv("PYUPSRS_WS_HOST", "0.0.0.0"),
        ws_port=int(os.getenv("PYUPSRS_WS_PORT", "10465")),
    )
