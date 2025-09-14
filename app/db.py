# app/db.py
from __future__ import annotations
import logging
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base
from .config import DATABASE_URL

log = logging.getLogger(__name__)

# ── URL normaliser: force psycopg v3 driver ───────────────────────────────────
def _normalize_db_url(url: str) -> str:
    if not url:
        return url
    u = url.strip()
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://"):]
    if u.startswith("postgresql+psycopg2://"):
        u = "postgresql+psycopg://" + u[len("postgresql+psycopg2://"):]
    if u.startswith("postgresql://"):
        u = "postgresql+psycopg://" + u[len("postgresql://"):]
    return u

DB_URL = _normalize_db_url(DATABASE_URL or "")
if not DB_URL:
    log.error("[DB] DATABASE_URL is empty!")
else:
    log.info("[DB] Using URL driver: %s", DB_URL.split("://", 1)[0])

# ── Engine & Session ──────────────────────────────────────────────────────────
engine = create_engine(
    DB_URL,
    pool_pre_ping=True,   # auto-recover stale connections
    future=True,
    echo=False,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
db_session = scoped_session(SessionLocal)

# ── Declarative Base (models import this) ─────────────────────────────────────
Base = declarative_base()

# ── Preflight checks (always) ─────────────────────────────────────────────────
def _preflight_db() -> None:
    """Assert psycopg v3 is active and the DB is reachable."""
    dbapi_name = getattr(engine.dialect.dbapi, "__name__", "")
    if "psycopg2" in dbapi_name:
        raise RuntimeError(
            "Driver mismatch: psycopg2 loaded. Install psycopg[binary]>=3.2 "
            "and ensure your URL starts with postgresql+psycopg://"
        )
    if "psycopg" not in dbapi_name:
        raise RuntimeError(
            f"Unexpected DBAPI '{dbapi_name}'. Expected psycopg v3; "
            "use postgresql+psycopg:// URLs."
        )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    log.info("[DB] Preflight OK (driver=%s)", dbapi_name)

# ── Optional guardrails (only if you opt in) ──────────────────────────────────
def _apply_guardrails() -> None:
    """Add columns the app expects; only used when schema is app-managed."""
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS package_type VARCHAR(16)"
        ))
    log.info("[DB] DDL guardrails applied (clients.package_type ensured)")

# ── Public init ───────────────────────────────────────────────────────────────
def init_db() -> None:
    """
    Startup routine.
    By default we DO NOT manage schema (external via psql/Render console).
    To allow the app to manage schema in dev, set DB_MANAGE_SCHEMA=1.
    """
    manage = os.environ.get("DB_MANAGE_SCHEMA", "0").lower() in ("1", "true", "yes")
    if manage:
        try:
            from . import models as _models  # noqa: F401
            Base.metadata.create_all(bind=engine)
            _apply_guardrails()
            log.info("[DB] App-managed schema: create_all + guardrails done")
        except Exception:
            log.exception("[DB] App-managed schema failed")
    else:
        log.info("[DB] External schema mode: skipping create_all and guardrails")

    _preflight_db()

def shutdown_session(exception: Exception | None = None) -> None:
    db_session.remove()
