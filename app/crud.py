# app/crud.py
from __future__ import annotations

from typing import Optional
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa


# ---------- Inbox logging (lead_messages) ----------
def log_lead_message(wa_number: str, direction: str, body: str, meta: Optional[dict] = None) -> None:
    """
    Write an inbound/outbound message to the inbox table.
    direction: 'in' | 'out'
    """
    wa = normalize_wa(wa_number)
    if not wa:
        return
    with get_session() as s:
        s.execute(
            text("""
                INSERT INTO lead_messages (wa_number, direction, body, meta)
                VALUES (:wa, :dir, :body, COALESCE(:meta, '{}'::jsonb))
            """),
            {"wa": wa, "dir": direction, "body": body or "", "meta": meta},
        )
        s.commit()


# ---------- Simple client lookups ----------
def client_exists_by_wa(wa_number: str) -> bool:
    wa = normalize_wa(wa_number)
    if not wa:
        return False
    with get_session() as s:
        row = s.execute(text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"), {"wa": wa}).first()
        return bool(row)


# ---------- (Keep/merge your existing helpers below) ----------
def find_next_upcoming_booking_by_wa(wa_number: str):
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


def list_clients(limit: int = 10, offset: int = 0) -> list[dict]:
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


def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> list[dict]:
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
