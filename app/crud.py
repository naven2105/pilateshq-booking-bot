# app/crud.py
from __future__ import annotations

from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa
from .config import TZ_NAME


# ─────────────────────────────────────────────────────────────────────────────
# Clients (public / admin)
# ─────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    """Return True if a client with this WhatsApp number exists."""
    wa = normalize_wa(wa_number)
    if not wa:
        return False
    with get_session() as s:
        row = s.execute(
            text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"),
            {"wa": wa},
        ).first()
        return bool(row)


def upsert_public_client(wa_number: str, name: str | None):
    """
    Ensure a client row exists for this WA number.

    - If name provided => set name (first time or keep existing if empty).
    - If name missing/blank => use 'Guest ####' (last 4 digits of WA).
    - Write a NON-NULL plan on insert (e.g., 'prospect') to satisfy schema.
    - Do NOT overwrite an existing plan on conflict.

    Returns dict(id, name, wa_number).
    """
    wa_norm = normalize_wa(wa_number)
    nm_in = (name or "").strip()

    last4 = wa_norm[-4:] if wa_norm and len(wa_norm) >= 4 else "0000"
    placeholder = f"Guest {last4}"

    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (
                    COALESCE(NULLIF(:name, ''), :placeholder),
                    :wa,
                    0,
                    'prospect'                  -- << set a safe non-null default
                )
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name)
                    -- plan is intentionally NOT overwritten here
                RETURNING id, name, wa_number
            """),
            {"name": nm_in, "placeholder": placeholder, "wa": wa_norm},
        ).mappings().first()
        return dict(row) if row else None


def list_clients(limit: int = 10, offset: int = 0) -> list[dict]:
    """Paginated list of clients for admin pickers."""
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                  id,
                  COALESCE(name,'')      AS name,
                  COALESCE(wa_number,'') AS wa_number,
                  COALESCE(plan,'')      AS plan,
                  COALESCE(credits,0)    AS credits
                FROM clients
                ORDER BY COALESCE(name,''), id
                LIMIT :lim OFFSET :off
            """),
            {"lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> list[dict]:
    """Case-insensitive search by name."""
    q = (q or "").strip()
    if not q:
        return list_clients(limit=limit, offset=offset)
    with get_session() as s:
        rows = s.execute(
            text("""
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
            """),
            {"needle": f"%{q}%", "lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Bookings / sessions
# ─────────────────────────────────────────────────────────────────────────────

def find_next_upcoming_booking_by_wa(wa_number: str):
    """Return the soonest future booking for this WA, using local (TZ_NAME) time."""
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                )
                SELECT
                    b.id     AS booking_id,
                    s.id     AS session_id,
                    s.session_date,
                    s.start_time,
                    c.id     AS client_id,
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


def create_cancel_request(client_id: int, session_id: int, reason: str | None = None) -> dict | None:
    """
    Log a client-initiated cancel request for admin to act on (no auto DB changes).
    Requires:

        CREATE TABLE IF NOT EXISTS cancel_requests (
          id SERIAL PRIMARY KEY,
          client_id INT NOT NULL REFERENCES clients(id),
          session_id INT NOT NULL REFERENCES sessions(id),
          reason TEXT,
          status TEXT NOT NULL DEFAULT 'pending',  -- pending | actioned | rejected
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO cancel_requests (client_id, session_id, reason, status)
                VALUES (:cid, :sid, :reason, 'pending')
                RETURNING id, client_id, session_id, reason, status, created_at
            """),
            {"cid": client_id, "sid": session_id, "reason": reason},
        ).mappings().first()
        return dict(row) if row else None
