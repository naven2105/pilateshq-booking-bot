# app/db.py
"""
Database Setup
--------------
Initialises SQLAlchemy engine, session, and Base.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session
import os

DATABASE_URL = os.getenv("DATABASE_URL")

# Create engine
engine = create_engine(DATABASE_URL, echo=False, future=True)

# Create a configured "Session" class
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

# Scoped session for thread safety (used across app)
db_session = scoped_session(SessionLocal)

# Base class for models
Base = declarative_base()

# Dependency helper
def get_db():
    """Yields a DB session (for FastAPI/Flask dependency style)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Ensure models import this Base
def init_db():
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
