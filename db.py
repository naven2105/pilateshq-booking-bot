# app/db.py
import os, logging
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
_engine = None
_Session = None

def init_db():
    global _engine, _Session
    if _engine: return
    _engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
    _Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    # sanity ping
    with _engine.connect() as c:
        c.execute(text("SELECT 1"))
    logging.info("DB ready")

@contextmanager
def get_session():
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

