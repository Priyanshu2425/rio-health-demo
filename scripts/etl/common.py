"""Helpers shared by the ETL scripts: paths and a sync DB connection."""

from __future__ import annotations

from pathlib import Path

import psycopg

from app.core.config import get_settings

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
RAW = DATA / "raw"
SEED = DATA / "seed"


def connect() -> psycopg.Connection:
    """Sync connection with search_path set to the app schema. Never logs the URL."""
    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("RIO_HEALTH_DATABASE_URL is not set (link the repo .env)")
    conn = psycopg.connect(settings.database_url)
    conn.execute(f"SET search_path TO {settings.db_schema}, public")
    return conn
