# app/db.py
"""
Database Setup
--------------
Initialises SQLAlchemy engine, session, and Base.
Normalises DATABASE_URL for SQLAlchemy + psycopg (v3) and hardens the pool.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session

# Get DB URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Ensure psycopg (v3) driver is used
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# Create engine with healthy pooling
# - pool_pre_ping: validates connections before use to avoid "EOF detected"
# - pool_recycle: recycle connections periodically to avoid stale SSL sessions
# - small pool sizing is fine for Render free/low tiers; adjust if needed
engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1800,  # seconds
    pool_size=5,
    max_overflow=5,
)

# Session factory + scoped session
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
db_session = scoped_session(SessionLocal)

# Base class for ORM models
Base = declarative_base()

def init_db():
    """Create tables if they don't exist."""
    import app.models  # ensures models are registered
    Base.metadata.create_all(bind=engine)
