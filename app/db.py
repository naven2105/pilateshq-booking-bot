# app/db.py
import os
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Read DB URL from env and force psycopg3 dialect
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
    """Create engine & session factory once; ping DB."""
    global _engine, _Session
    if _engine:
        return
    _engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        future=True,
    )
    _Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    # sanity ping
    with _engine.connect() as c:
        c.execute(text("SELECT 1"))
    logging.info("[DB] Ready")

@contextmanager
def get_session():
    """Yield a SQLAlchemy session with commit/rollback handling."""
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
