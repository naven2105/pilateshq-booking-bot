# app/crud.py
from __future__ import annotations

from typing import Optional, List, Dict
from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa


# ──────────────────────────────────────────────────────────────────────────────
# Clients
# ──────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    """
    True if a client with this WA number exists (normalized).
    """
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(
            text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"),
            {"wa": wa},
        ).first()
        return bool(row)


def upsert_public_client(wa_number: str, name: Optional[str]) -> Dict:
    """
    Create or gently update a *lead* client.
    - Ensures NOT NULL constraints are respected (name & plan).
    - If name is empty/None, uses a placeholder like 'Guest 4607'.
    - plan is set to 'lead' (adjust if your schema has a different default).
    """
    wa = normalize_wa(wa_number)

    # Derive a friendly placeholder if name missing/blank
    name_clean = (name or "").strip()
    if not name_clean:
        last4 = wa[-4:] if len(wa) >= 4 else "lead"
        name_clean = f"Guest {last4}"

    with get_session() as s:
        row = s.execute(
            text(
                """
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (:name, :wa, 0, 'lead')
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name),
                    plan = COALESCE(clients.plan, 'lead')
                RETURNING id, name, wa_number
                """
            ),
            {"name": name_clean, "wa": wa},
        ).mappings().first()
        return dict(row)  # {id, name, wa_number}


def list_clients(limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Paginated list of clients for admin pickers.
    """
    with get_session() as s:
        rows = s.execute(
            text(
                """
                SELECT
                    id,
                    COALESCE(name,'')      AS name,
                    COALESCE(wa_number,'') AS wa_number,
                    COALESCE(plan,'')      AS plan,
                    COALESCE(credits,0)    AS credits
                FROM clients
                ORDER BY COALESCE(name,''), id
                LIMIT :lim OFFSET :off
                """
            ),
            {"lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Case-insensitive name search; returns same brief shape as list_clients.
    """
    q = (q or "").strip()
    if not q:
        return list_clients(limit=limit, offset=offset)

    with get_session() as s:
        rows = s.execute(
            text(
                """
                SELECT
                    id,
                    COALESCE(name,'')      AS name,
                    COALESCE(wa_number,'') AS wa_number,
                    COALESCE(plan,'')      AS plan,
                    COALESCE(credits,0)    AS credits
                FROM clients
                WHERE LOWER(COALESCE(name,'')) LIKE LOWER(:needle)
                ORDER BY COALESCE(name,''), id
                LIMIT :lim OFFSET :off
                """
            ),
            {"needle": f"%{q}%", "lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Bookings / Sessions (used by client cancel flow, lookups, etc.)
# ──────────────────────────────────────────────────────────────────────────────

def find_next_upcoming_booking_by_wa(wa_number: str) -> Optional[Dict]:
    """
    Returns the soonest future confirmed booking for this WA number (local SA time).
    Shape: {booking_id, session_id, session_date, start_time, client_id, name, wa_number}
    """
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(
            text(
                """
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
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
                """
            ),
            {"wa": wa},
        ).mappings().first()
        return dict(row) if row else None


def cancel_all_future_bookings_by_wa(wa_number: str) -> int:
    """
    Marks all *future* bookings for this WA as 'cancel_requested'.
    Returns count affected. (Admin can later action them.)
    """
    wa = normalize_wa(wa_number)
    with get_session() as s:
        res = s.execute(
            text(
                """
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
                )
                UPDATE bookings b
                SET status = 'cancel_requested'
                FROM clients c, sessions s, now_local
                WHERE b.client_id = c.id
                  AND b.session_id = s.id
                  AND c.wa_number = :wa
                  AND b.status = 'confirmed'
                  AND (s.session_date + s.start_time) > now_local.ts
                """
            ),
            {"wa": wa},
        )
        return res.rowcount or 0


# ──────────────────────────────────────────────────────────────────────────────
# Optional — Admin-side triage (only used if you wire it up)
# ──────────────────────────────────────────────────────────────────────────────

def create_cancel_request(booking_id: int, reason: Optional[str], source_wa: Optional[str]) -> Dict:
    """
    Inserts a row into a (hypothetical) cancel_requests table to track admin workflow.
    Implement this table if you intend to use it:

        CREATE TABLE IF NOT EXISTS cancel_requests (
            id SERIAL PRIMARY KEY,
            booking_id INT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
            source_wa  TEXT,
            reason     TEXT,
            status     TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

    Returns {id, booking_id, status}.
    """
    with get_session() as s:
        row = s.execute(
            text(
                """
                INSERT INTO cancel_requests (booking_id, source_wa, reason, status)
                VALUES (:bid, :wa, :reason, 'open')
                RETURNING id, booking_id, status
                """
            ),
            {"bid": int(booking_id), "wa": normalize_wa(source_wa or ""), "reason": reason},
        ).mappings().first()
        return dict(row)
