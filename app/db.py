# app/db.py
from __future__ import annotations
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from .config import DATABASE_URL

log = logging.getLogger(__name__)

# ── URL normaliser: force psycopg v3 driver ───────────────────────────────────
def _normalize_db_url(url: str) -> str:
    """
    Ensure SQLAlchemy uses psycopg v3 (not psycopg2).
    - postgres://        -> postgresql+psycopg://
    - postgresql://      -> postgresql+psycopg://
    - postgresql+psycopg2:// -> postgresql+psycopg://
    """
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

# ── Preflight checks ──────────────────────────────────────────────────────────
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
        conn.execute(text("SELECT current_database()"))
    log.info("[DB] Preflight OK (driver=%s)", dbapi_name)

# ── Idempotent DDL guardrails ─────────────────────────────────────────────────
def _apply_guardrails() -> None:
    """Add columns the app expects; safe to run every startup."""
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS package_type VARCHAR(16)"
        ))
    log.info("[DB] DDL guardrails applied (clients.package_type ensured)")

# ── Public init ───────────────────────────────────────────────────────────────
def init_db() -> None:
    """
    Startup routine:
    1) Apply guardrails (keeps runtime safe even before migrations run).
    2) Preflight driver + connectivity and fail-fast if wrong.
    """
    try:
        _apply_guardrails()
    except Exception:
        log.exception("[DB] Guardrails failed")
        # continue to preflight to surface driver errors too
    _preflight_db()

def shutdown_session(exception: Exception | None = None) -> None:
    db_session.remove()
