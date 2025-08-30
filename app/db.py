# app/db.py
"""
Database engine & session lifecycle using SQLAlchemy 2.x style.
- Normalizes DATABASE_URL to psycopg3
- Creates a single engine and session factory
- Provides get_session() context manager with commit/rollback
"""

import os
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Read DB URL from env and force psycopg3 dialect if needed.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    logging.warning("[DB] DATABASE_URL is not set")

# Normalize scheme → psycopg3 driver
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

_engine = None
_Session = None

def init_db():
    """
    Create the engine & session factory once and sanity-ping the DB.
    Called lazily on first request (see app/main.py).
    """
    global _engine, _Session
    if _engine:
        return
    _engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # validates connections before using
        future=True,         # 2.x style execution
    )
    _Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)

    # Sanity ping (raises if credentials/network wrong)
    with _engine.connect() as c:
        c.execute(text("SELECT 1"))
    logging.info("[DB] Ready")

@contextmanager
def get_session():
    """
    Usage:
        with get_session() as s:
            s.execute(...)
    Guarantees commit on success, rollback on exception, and close.
    """
    if _Session is None:
        init_db()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
