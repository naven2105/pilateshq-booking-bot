# app/crud.py
from __future__ import annotations

from typing import Optional, List, Dict
from sqlalchemy import text
from .db import get_session
from .config import TZ_NAME  # e.g. "Africa/Johannesburg"


# ──────────────────────────────────────────────────────────────────────────────
# BOOKINGS / UPCOMING
# ──────────────────────────────────────────────────────────────────────────────

def find_next_upcoming_booking_by_wa(wa_number: str) -> Optional[Dict]:
    """
    Return the next upcoming confirmed booking (soonest future session) for this
    WhatsApp number, or None if not found.

    Notes:
    - Time comparisons are done in local time (TZ_NAME) by converting DB now().
    - We compare (session_date + start_time) to local 'now' for correctness.
    """
    from .utils import normalize_wa
    wa = normalize_wa(wa_number)

    with get_session() as s:
        row = s.execute(
            text(f"""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                )
                SELECT
                    b.id AS booking_id,
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
            """),
            {"wa": wa, "tz": TZ_NAME},
        ).mappings().first()
        return dict(row) if row else None


# ──────────────────────────────────────────────────────────────────────────────
# CLIENT LISTING / SEARCH (used by admin picker)
# ──────────────────────────────────────────────────────────────────────────────

def list_clients(limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Return a simple paginated list of clients for the admin picker.
    Sorted by name then id. Fields kept small to fit WhatsApp list rows.
    """
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


def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Case-insensitive search by name (substring). Falls back to list if query is empty.

    Implementation:
    - Uses ILIKE for case-insensitive contains. For very large tables, consider
      adding a trigram index or switching name column to CITEXT type.
    """
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
                WHERE COALESCE(name, '') ILIKE :needle
                ORDER BY COALESCE(name, ''), id
                LIMIT :lim OFFSET :off
            """),
            {"needle": f"%{q}%", "lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# SESSIONS (tiny helper referenced by admin flow)
# ──────────────────────────────────────────────────────────────────────────────

def find_session_by_date_time(d_iso: str, hhmm: str) -> Optional[Dict]:
    """
    Look up a session row by exact date string 'YYYY-MM-DD' and time 'HH:MM'.
    Returns mapping {id, session_date, start_time, capacity, booked_count, status, notes} or None.

    Useful for command: BOOK "<Name>" ON YYYY-MM-DD HH:MM
    """
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT
                    id,
                    session_date,
                    start_time,
                    capacity,
                    booked_count,
                    status,
                    COALESCE(notes,'') AS notes
                FROM sessions
                WHERE session_date = :d::date
                  AND start_time   = :t::time
                LIMIT 1
            """),
            {"d": d_iso, "t": hhmm},
        ).mappings().first()
        return dict(row) if row else None
