from __future__ import annotations

from typing import Optional, Dict, Any
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
import re

# Prefer Psycopg v3 driver; normalize URL if needed
RAW_DB_URL = os.environ.get("DATABASE_URL", "").strip()

def _normalize_db_url(url: str) -> str:
    if not url:
        return "sqlite+pysqlite:///:memory:"
    url = re.sub(r"^postgres://", "postgresql://", url)
    url = re.sub(r"^postgresql\+psycopg2://", "postgresql+psycopg://", url)
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url

DATABASE_URL = _normalize_db_url(RAW_DB_URL)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
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

# Minimal number normalizer (uses project utils if available)
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
# Clients
# ──────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa: str) -> bool:
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
    Idempotent insert/update of a client record.
    Matches your current schema (no new columns required).
    """
    wa_norm = normalize_wa(wa)
    with session_scope() as s:
        existing = s.execute(
            text("""
                SELECT id, wa_number, name
                FROM clients
                WHERE wa_number = :wa_norm OR wa_number = :wa_plus
                LIMIT 1
            """),
            {"wa_norm": wa_norm, "wa_plus": f"+{wa_norm}"},
        ).mappings().first()

        if existing:
            s.execute(
                text("""
                    UPDATE clients
                    SET wa_number = :wa_norm,
                        name = COALESCE(:name, name)
                    WHERE id = :id
                """),
                {"wa_norm": wa_norm, "name": name, "id": existing["id"]},
            )
            return {"id": existing["id"], "wa_number": wa_norm, "name": name or existing.get("name")}

        row = s.execute(
            text("""
                INSERT INTO clients (wa_number, name)
                VALUES (:wa_norm, COALESCE(:name, 'Guest'))
                RETURNING id
            """),
            {"wa_norm": wa_norm, "name": name},
        ).mappings().first()
        return {"id": row["id"], "wa_number": wa_norm, "name": name}

# ──────────────────────────────────────────────────────────────────────────────
# Leads
# ──────────────────────────────────────────────────────────────────────────────

def record_lead_touch(wa: str, name: Optional[str] = None) -> Dict[str, Any]:
    """
    Upsert lead in `leads` table and return whether this is a returning lead.
    No schema changes required. Uses `last_contact` to track freshness.
    """
    wa_norm = normalize_wa(wa)
    wa_plus = f"+{wa_norm}"
    with session_scope() as s:
        existing = s.execute(
            text("""
                SELECT id, name, status
                FROM leads
                WHERE wa_number = :wa_norm OR wa_number = :wa_plus
                LIMIT 1
            """),
            {"wa_norm": wa_norm, "wa_plus": wa_plus},
        ).mappings().first()

        if existing:
            s.execute(
                text("""
                    UPDATE leads
                    SET last_contact = now(),
                        name = COALESCE(:name, name)
                    WHERE id = :id
                """),
                {"id": existing["id"], "name": name},
            )
            return {
                "returning": True,
                "lead_id": existing["id"],
                "status": existing.get("status") or "new",
                "name": name or existing.get("name"),
            }

        ins = s.execute(
            text("""
                INSERT INTO leads (wa_number, name, status)
                VALUES (:wa, :name, 'new')
                RETURNING id
            """),
            {"wa": wa_norm, "name": name},
        ).mappings().first()
        return {"returning": False, "lead_id": ins["id"], "status": "new", "name": name}

# ──────────────────────────────────────────────────────────────────────────────
# Admin inbox
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
