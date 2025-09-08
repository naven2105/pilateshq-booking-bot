# app/crud.py
from __future__ import annotations
import hashlib, json
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _digest(kind: str, title: str, body: str,
            session_id: Optional[int], client_id: Optional[int],
            bucket: str) -> str:
    payload = {"k": kind, "t": title, "b": body, "s": session_id, "c": client_id, "bk": bucket}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

# ─────────────────────────────────────────────────────────────────────────────
# Clients / Sessions / Bookings (existing & used across the app)
# ─────────────────────────────────────────────────────────────────────────────

def find_next_upcoming_booking_by_wa(wa_number: str) -> Optional[Dict[str, Any]]:
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT b.id AS booking_id,
                   s.id AS session_id,
                   s.session_date,
                   s.start_time,
                   c.id AS client_id,
                   c.name,
                   c.wa_number
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            JOIN clients  c ON c.id = b.client_id
            , now_local
            WHERE c.wa_number = :wa
              AND b.status = 'confirmed'
              AND (s.session_date + s.start_time) > now_local.ts
            ORDER BY s.session_date, s.start_time
            LIMIT 1
        """), {"wa": wa}).mappings().first()
        return dict(row) if row else None

def list_clients(limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                    id,
                    COALESCE(name, '')       AS name,
                    COALESCE(wa_number, '')  AS wa_number,
                    COALESCE(plan, '')       AS plan,
                    COALESCE(credits, 0)     AS credits
                FROM clients
                ORDER BY COALESCE(name, ''), id
                LIMIT :lim OFFSET :off
            """),
            {"lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]

def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    q = (q or "").strip()
    if not q:
        return list_clients(limit=limit, offset=offset)
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                    id,
                    COALESCE(name, '')       AS name,
                    COALESCE(wa_number, '')  AS wa_number,
                    COALESCE(plan, '')       AS plan,
                    COALESCE(credits, 0)     AS credits
                FROM clients
                WHERE LOWER(COALESCE(name, '')) LIKE LOWER(:needle)
                ORDER BY COALESCE(name, ''), id
                LIMIT :lim OFFSET :off
            """),
            {"needle": f"%{q}%", "lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]

def upsert_public_client(wa_number: str, name: Optional[str]) -> Dict[str, Any]:
    """
    Create or update a lightweight client row when a public user talks to us.
    Ensures name is never NULL (fallback 'Guest ####').
    """
    wa_norm = normalize_wa(wa_number)
    # fallback display name like "Guest 4607"
    tail = wa_norm[-4:] if wa_norm and len(wa_norm) >= 4 else "0000"
    placeholder = f"Guest {tail}"
    safe_name = (name or "").strip()

    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (COALESCE(NULLIF(:name,''), :placeholder), :wa, 0, '')
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name,''), clients.name)
                RETURNING id, name, wa_number
            """),
            {"name": safe_name, "placeholder": placeholder, "wa": wa_norm},
        ).mappings().first()
        return dict(row)

def client_exists_by_wa(wa_number: str) -> bool:
    with get_session() as s:
        row = s.execute(text("""
            SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1
        """), {"wa": normalize_wa(wa_number)}).first()
        return bool(row)

# ─────────────────────────────────────────────────────────────────────────────
# Admin Inbox
# ─────────────────────────────────────────────────────────────────────────────

def inbox_upsert(kind: str, title: str, body: str,
                 bucket: str,
                 source: str = "system",
                 session_id: Optional[int] = None,
                 client_id: Optional[int] = None,
                 status: str = "open") -> Optional[int]:
    """
    Idempotent insert using digest(bucketed). Returns the existing/new id, or None on no-op.
    """
    dg = _digest(kind, title, body, session_id, client_id, bucket)
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO admin_inbox (kind, title, body, session_id, client_id, source, status, bucket, digest)
                VALUES (:k, :t, :b, :sid, :cid, :src, :st, :bk, :dg)
                ON CONFLICT (digest) DO NOTHING
                RETURNING id
            """),
            {"k": kind, "t": title, "b": body, "sid": session_id, "cid": client_id,
             "src": source, "st": status, "bk": bucket, "dg": dg}
        ).mappings().first()
        return row["id"] if row else None

def inbox_recent(limit_per_kind: int = 5) -> Dict[str, List[Dict[str, Any]]]:
    """
    Return last N items per kind (hourly, daily, query, proposal), newest first.
    """
    kinds = ["proposal", "query", "hourly", "daily"]
    out: Dict[str, List[Dict[str, Any]]] = {}
    with get_session() as s:
        for k in kinds:
            rows = s.execute(
                text("""
                    SELECT id, kind, title, body, session_id, client_id, source, status, bucket, created_at
                    FROM admin_inbox
                    WHERE kind = :k
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"k": k, "lim": int(limit_per_kind)}
            ).mappings().all()
            out[k] = [dict(r) for r in rows]
    return out

def inbox_counts_by_kind() -> Dict[str, int]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT kind, COUNT(*) AS n
            FROM admin_inbox
            GROUP BY kind
        """)).mappings().all()
    return {r["kind"]: int(r["n"]) for r in rows}

def inbox_get(id_: int) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT id, kind, title, body, session_id, client_id, source, status, bucket, created_at
                FROM admin_inbox
                WHERE id = :i
            """),
            {"i": int(id_)}
        ).mappings().first()
        return dict(row) if row else None

def inbox_mark_closed(id_: int) -> None:
    with get_session() as s:
        s.execute(text("""
            UPDATE admin_inbox SET status = 'closed' WHERE id = :i
        """), {"i": int(id_)})
