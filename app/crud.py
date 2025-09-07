# app/crud.py

from __future__ import annotations
from typing import Optional, List, Dict

from sqlalchemy import text
from .db import get_session


# ──────────────────────────────────────────────────────────────────────────────
# Public client utilities
# ──────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    """
    True if a client record exists for this normalized WhatsApp number.
    Assumes a UNIQUE constraint on clients.wa_number.
    """
    from .utils import normalize_wa
    wa = normalize_wa(wa_number)
    if not wa:
        return False
    with get_session() as s:
        row = s.execute(
            text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"),
            {"wa": wa},
        ).first()
        return bool(row)


def upsert_public_client(wa: str, name: Optional[str] = None) -> Dict:
    """
    Create or update a 'public' client row by WhatsApp number.
    - If the WA number exists, update the name only when a non-empty name is given.
    - If it doesn't exist, insert a minimal client (name may be NULL) with credits=0.

    Returns: {id, name, wa_number}
    """
    from .utils import normalize_wa
    wa_norm = normalize_wa(wa)
    if not wa_norm:
        raise ValueError("Invalid WA number for upsert_public_client")

    with get_session() as s:
        # Ensure the column wa_number has a UNIQUE index in your schema.
        # We only update name if a new non-null value is supplied.
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (:name, :wa, 0, NULL)
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(EXCLUDED.name, clients.name)
                RETURNING id, name, wa_number
            """),
            {"name": name if (name and name.strip()) else None, "wa": wa_norm},
        ).mappings().first()
        return dict(row) if row else {"id": None, "name": name, "wa_number": wa_norm}


# ──────────────────────────────────────────────────────────────────────────────
# Booking lookup helpers
# ──────────────────────────────────────────────────────────────────────────────

def find_next_upcoming_booking_by_wa(wa_number: str) -> Optional[Dict]:
    """
    Return the next upcoming booking (soonest future session) for this WA number,
    or None if not found. Local time Africa/Johannesburg.
    """
    from .utils import normalize_wa
    wa = normalize_wa(wa_number)
    if not wa:
        return None
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


# ──────────────────────────────────────────────────────────────────────────────
# Admin pickers / search
# ──────────────────────────────────────────────────────────────────────────────

def list_clients(limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Simple paginated list of clients for admin pickers.
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
    Case-insensitive substring search by name.
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
                WHERE LOWER(COALESCE(name, '')) LIKE LOWER(:needle)
                ORDER BY COALESCE(name, ''), id
                LIMIT :lim OFFSET :off
            """),
            {"needle": f"%{q}%", "lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Optional: admin cancellation requests queue
# ──────────────────────────────────────────────────────────────────────────────

def create_cancel_request(client_id: int, session_id: int, source: str = "client") -> Dict:
    """
    Enqueue a cancellation request for admin to review later.
    Requires a table cancel_requests(client_id, session_id, source, created_at, status).
    """
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO cancel_requests (client_id, session_id, source, status)
                VALUES (:cid, :sid, :src, 'pending')
                RETURNING id, client_id, session_id, source, status, created_at
            """),
            {"cid": int(client_id), "sid": int(session_id), "src": source},
        ).mappings().first()
        return dict(row)
