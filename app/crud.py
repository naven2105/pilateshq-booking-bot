# app/crud.py
from __future__ import annotations
from typing import Optional, List, Dict
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa


# ─────────────────────────────────────────────────────────────────────────────
# Clients (for admin pickers & search)
# ─────────────────────────────────────────────────────────────────────────────

def list_clients(limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Paginated client list for admin pickers.
    """
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                    id,
                    COALESCE(name, '')      AS name,
                    COALESCE(wa_number, '') AS wa_number,
                    COALESCE(plan, '')      AS plan,
                    COALESCE(credits, 0)    AS credits
                FROM clients
                ORDER BY COALESCE(name, ''), id
                LIMIT :lim OFFSET :off
            """),
            {"lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Case-insensitive substring search on client name.
    """
    q = (q or "").strip()
    if not q:
        return list_clients(limit=limit, offset=offset)

    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                    id,
                    COALESCE(name, '')      AS name,
                    COALESCE(wa_number, '') AS wa_number,
                    COALESCE(plan, '')      AS plan,
                    COALESCE(credits, 0)    AS credits
                FROM clients
                WHERE LOWER(COALESCE(name, '')) LIKE LOWER(:needle)
                ORDER BY COALESCE(name, ''), id
                LIMIT :lim OFFSET :off
            """),
            {"needle": f"%{q}%", "lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Bookings lookups
# ─────────────────────────────────────────────────────────────────────────────

def find_next_upcoming_booking_by_wa(wa_number: str) -> Optional[Dict]:
    """
    Return the next upcoming (soonest future) confirmed booking for a WA number.
    Times are compared in Africa/Johannesburg local time.
    """
    from .utils import normalize_wa
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT
                b.id  AS booking_id,
                s.id  AS session_id,
                s.session_date,
                s.start_time,
                c.id  AS client_id,
                COALESCE(c.name, '')      AS name,
                COALESCE(c.wa_number, '') AS wa_number
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            JOIN clients  c ON c.id = b.client_id,
                 now_local
            WHERE c.wa_number = :wa
              AND b.status = 'confirmed'
              AND (s.session_date + s.start_time) > now_local.ts
            ORDER BY s.session_date, s.start_time
            LIMIT 1
        """), {"wa": wa}).mappings().first()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Cancellation requests (client-initiated or admin-logged)
# ─────────────────────────────────────────────────────────────────────────────

def create_cancel_request(
    client_id: int,
    session_id: int,
    source: str = "client",
    reason: Optional[str] = None,
) -> int:
    """
    Log a cancellation REQUEST (does NOT change the booking or session).
    Admin can later review/approve and perform the actual cancellation + credit logic.

    Returns: new cancel_requests.id
    """
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO cancel_requests (client_id, session_id, source, reason)
                VALUES (:client_id, :session_id, :source, :reason)
                RETURNING id
            """),
            {
                "client_id": int(client_id),
                "session_id": int(session_id),
                "source": (source or "client"),
                "reason": reason,
            },
        ).mappings().first()
        return int(row["id"])

def client_exists_by_wa(raw_wa: str) -> bool:
    """
    Return True if a client with this WhatsApp number exists (after normalization), else False.
    """
    wa = normalize_wa(raw_wa or "")
    if not wa:
        return False
    with get_session() as s:
        row = s.execute(
            text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"),
            {"wa": wa},
        ).first()
        return row is not None

def get_client_by_wa(raw_wa: str) -> dict | None:
    """
    Fetch a minimal client record by WA number; returns dict or None.
    """
    wa = normalize_wa(raw_wa or "")
    if not wa:
        return None
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT id, name, wa_number, plan, credits
                FROM clients
                WHERE wa_number = :wa
                LIMIT 1
            """),
            {"wa": wa},
        ).mappings().first()
        return dict(row) if row else None