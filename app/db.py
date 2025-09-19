# app/db.py
"""
Database session helper.
Provides get_session() context manager for use with SQLAlchemy Core/ORM.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

# Database URL from environment (e.g. postgres://...)
DATABASE_URL = os.getenv("DATABASE_URL")

# Create engine with connection pool
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_session():
    """
    Context-managed session.
    Example:
        with get_session() as s:
            rows = s.execute(text("SELECT * FROM clients")).mappings().all()
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
