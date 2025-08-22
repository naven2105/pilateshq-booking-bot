# db.py  — psycopg3 + SQLAlchemy
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

raw_url = os.environ.get("DATABASE_URL")
if not raw_url:
    raise RuntimeError("DATABASE_URL not set")

def _normalize(url: str) -> str:
    # Render may give postgres:// or postgresql://
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url.split("postgresql://", 1)[1]
    return url

DATABASE_URL = _normalize(raw_url)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

def get_session():
    """Usage: with get_session() as s: ..."""
    return SessionLocal()

def init_db():
    """Create tables once per process (idempotent). Called from main.py @before_serving."""
    # Import models inside to avoid circular imports
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
