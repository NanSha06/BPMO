"""
config_loader.py
================
Single import point for all configuration across the platform.

Every module that needs config or env vars does:

    from config_loader import config, env

    db_user = env("DB_USER")
    chunk   = config["etl"]["chunk_size"]
"""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Resolve paths relative to this file's location
_ROOT = Path(__file__).parent
_ENV_PATH    = _ROOT / ".env"
_CONFIG_PATH = _ROOT / "config.yaml"


# ── Load .env into os.environ ────────────────────────────────
if not _ENV_PATH.exists():
    raise FileNotFoundError(
        f".env file not found at {_ENV_PATH}\n"
        f"Copy the provided .env template to your project root and fill in your values."
    )
load_dotenv(_ENV_PATH)


# ── Load config.yaml ─────────────────────────────────────────
if not _CONFIG_PATH.exists():
    raise FileNotFoundError(
        f"config.yaml not found at {_CONFIG_PATH}\n"
        f"Copy the provided config.yaml template to your project root."
    )
with open(_CONFIG_PATH, "r") as f:
    config: dict = yaml.safe_load(f)


# ── env() helper ─────────────────────────────────────────────
def env(key: str, default: str = None) -> str:
    """
    Read an environment variable loaded from .env.
    Raises KeyError if the variable is missing and no default given.

    Usage:
        db_pass = env("DB_PASSWORD")
        api_key = env("GEMINI_API_KEY", default="")
    """
    value = os.getenv(key, default)
    if value is None:
        raise KeyError(
            f"Environment variable '{key}' is not set.\n"
            f"Add it to your .env file."
        )
    return value


# ── Pre-built database URL ───────────────────────────────────
def get_database_url() -> str:
    """
    Build and return the PostgreSQL connection URL from .env values.
    Use this instead of hard-coding credentials anywhere.

    Usage:
        from config_loader import get_database_url
        from sqlalchemy import create_engine
        engine = create_engine(get_database_url())
    """
    return (
        f"postgresql://{env('DB_USER')}:{env('DB_PASSWORD')}"
        f"@{env('DB_HOST')}:{env('DB_PORT')}/{env('DB_NAME')}"
    )