# app/db.py
from __future__ import annotations
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from .config import DATABASE_URL

log = logging.getLogger(__name__)

# Create the engine with sane defaults for Render + Postgres
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # recover stale connections
    future=True,
    echo=False,
)

# Unit-of-work session factory + scoped session for thread safety
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
db_session = scoped_session(SessionLocal)


def init_db() -> None:
    """
    Initialise DB 'guardrails':
    - Add columns that our ORM expects but the physical table might still miss.
    - Idempotent and safe to run on every startup.
    """
    try:
        with engine.begin() as conn:
            # Ensure clients.package_type exists (nullable short text)
            conn.execute(text(
                "ALTER TABLE clients ADD COLUMN IF NOT EXISTS package_type VARCHAR(16)"
            ))
        log.info("[DB] DDL guardrails applied (clients.package_type ensured)")
    except Exception:
        log.exception("[DB] DDL guardrails failed")


def shutdown_session(exception: Exception | None = None) -> None:
    """Optional teardown hook (not strictly required)."""
    db_session.remove()
