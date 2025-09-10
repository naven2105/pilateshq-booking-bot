# app/crud.py
from __future__ import annotations

from typing import Optional, Dict, Any
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
import re

# Try to import the project's normalizer
try:
    from .utils import normalize_wa
except Exception:
    def normalize_wa(wa: str) -> str:
        wa = (wa or "").strip().replace(" ", "")
        if wa.startswith("+"):
            wa = wa[1:]
        if wa.startswith("0") and len(wa) >= 10:
            return "27" + wa[1:]
        return wa

# ──────────────────────────────────────────────────────────────────────────────
# Database URL normalization
# ──────────────────────────────────────────────────────────────────────────────
# Prefer Psycopg v3 driver. If DATABASE_URL is plain 'postgresql://' or '+psycopg2',
# rewrite it to 'postgresql+psycopg://'.
RAW_DB_URL = os.environ.get("DATABASE_URL", "").strip()

def _normalize_db_url(url: str) -> str:
    if not url:
        # Local dev fallback (SQLite memory) to avoid boot failures without DB
        return "sqlite+pysqlite:///:memory:"
    # If already psycopg v3 driver, keep it
    if url.startswith("postgresql+psycopg://"):
        return url
    # Convert 'postgresql://' or 'postgres://' or 'postgresql+psycopg2://' → psycopg v3
    url = re.sub(r"^postgres://", "postgresql://", url)  # legacy heroku-style
    url = re.sub(r"^postgresql\+psycopg2://", "postgresql+psycopg://", url)
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url

DATABASE_URL = _normalize_db_url(RAW_DB_URL)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    # For SQLite memory fallback, disable thread check
    connect_args=({"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()

# ──────────────────────────────────────────────────────────────────────────────
# Clients
# ──────────────────────────────────────────────────────────────────────────────
def client_exists_by_wa(wa: str) -> bool:
    """
    Return True if a client exists for this WA number.
    Compare normalized '27...' and '+27...' WITHOUT SQL concatenation
    to avoid Postgres text/varchar ambiguity.
    """
    wa_norm = normalize_wa(wa)
    wa_plus = f"+{wa_norm}"
    with session_scope() as s:
        row = s.execute(
            text("""
                SELECT 1
                FROM clients
                WHERE wa_number = :wa_norm OR wa_number = :wa_plus
                LIMIT 1
            """),
            {"wa_norm": wa_norm, "wa_plus": wa_plus},
        ).first()
        return bool(row)

def upsert_public_client(wa: str, name: Optional[str]) -> Dict[str, Any]:
    """
    Idempotent insert/update of a 'lead' client. Always stores normalized WA.
    If a '+...' record exists, update it to normalized form.
    """
    wa_norm = normalize_wa(wa)
    with session_scope() as s:
        # Fetch if exists under either form
        row = s.execute(
            text("""
                SELECT id, wa_number, name
                FROM clients
                WHERE wa_number = :wa_norm OR wa_number = :wa_plus
                LIMIT 1
            """),
            {"wa_norm": wa_norm, "wa_plus": f"+{wa_norm}"},
        ).mappings().first()

        if row:
            s.execute(
                text("""
                    UPDATE clients
                    SET wa_number = :wa_norm,
                        name = COALESCE(:name, name)
                    WHERE id = :id
                """),
                {"wa_norm": wa_norm, "name": name, "id": row["id"]},
            )
            return {"id": row["id"], "wa_number": wa_norm, "name": name or row.get("name")}
        else:
            ins = s.execute(
                text("""
                    INSERT INTO clients (wa_number, name, role)
                    VALUES (:wa_norm, :name, 'lead')
                    RETURNING id
                """),
                {"wa_norm": wa_norm, "name": name},
            ).mappings().first()
            return {"id": ins["id"], "wa_number": wa_norm, "name": name}

# ──────────────────────────────────────────────────────────────────────────────
# Admin inbox (minimal)
# ──────────────────────────────────────────────────────────────────────────────
def inbox_upsert(
    *,
    kind: str,
    title: str,
    body: str,
    source: str,
    status: str,
    is_unread: bool,
    action_required: bool,
    digest: str,
) -> Dict[str, Any]:
    """
    Idempotent-ish insert using a unique digest. If digest exists, return existing id.
    """
    with session_scope() as s:
        existing = s.execute(
            text("SELECT id FROM admin_inbox WHERE digest = :digest LIMIT 1"),
            {"digest": digest},
        ).mappings().first()
        if existing:
            return {"id": existing["id"], "deduped": True}

        row = s.execute(
            text("""
                INSERT INTO admin_inbox (kind, title, body, source, status, is_unread, action_required, digest)
                VALUES (:kind, :title, :body, :source, :status, :is_unread, :action_required, :digest)
                RETURNING id
            """),
            {
                "kind": kind,
                "title": title,
                "body": body,
                "source": source,
                "status": status,
                "is_unread": is_unread,
                "action_required": action_required,
                "digest": digest,
            },
        ).mappings().first()
        return {"id": row["id"], "deduped": False}
