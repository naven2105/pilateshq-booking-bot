# app/db.py
"""
Database Setup
--------------
Initialises SQLAlchemy engine, session, and Base.
Normalises DATABASE_URL for SQLAlchemy + psycopg (v3).
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

# Create engine
engine = create_engine(DATABASE_URL, echo=False, future=True)

# Session factory
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

# Scoped session (thread-safe for Flask + Gunicorn)
db_session = scoped_session(SessionLocal)

# Base class for ORM models
Base = declarative_base()

def init_db():
    import app.models  # ensures models are registered
    Base.metadata.create_all(bind=engine)
