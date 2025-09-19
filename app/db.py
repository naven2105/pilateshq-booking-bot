# app/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import contextlib

# ── Database URL ────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Engine and Session factory ──────────────────────────────────
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# ── Declarative Base for ORM models ─────────────────────────────
Base = declarative_base()

# ── Session helper ──────────────────────────────────────────────
@contextlib.contextmanager
def get_session():
    """
    Provide a transactional scope around a series of operations.
    Usage:
        with get_session() as s:
            s.execute(...)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
