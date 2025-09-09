# app/crud.py
from __future__ import annotations

from hashlib import sha256
from typing import Optional, List, Dict

from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa


# ──────────────────────────────────────────────────────────────────────────────
# Clients
# ──────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    wa = normalize_wa(wa_number)
    sql = text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1")
    with get_session() as s:
        return s.execute(sql, {"wa": wa}).scalar() is not None


def find_client_by_wa(wa_number: str) -> Optional[Dict]:
    wa = normalize_wa(wa_number)
    sql = text("""
        SELECT id, name, wa_number, plan, credits
        FROM clients
        WHERE wa_number = :wa
        LIMIT 1
    """)
    with get_session() as s:
        row = s.execute(sql, {"wa": wa}).mappings().first()
        return dict(row) if row else None


def find_one_client(client_id: int) -> Optional[Dict]:
    """
    Return a single client by id (or None).
    """
    sql = text("""
        SELECT id, name, wa_number, plan, credits
        FROM clients
        WHERE id = :cid
        LIMIT 1
    """)
    with get_session() as s:
        row = s.execute(sql, {"cid": int(client_id)}).mappings().first()
        return dict(row) if row else None


def upsert_public_client(wa_number: str, name: Optional[str]) -> Dict:
    """
    Ensure a client row exists for this WA number.
    If name is empty/None, store a lightweight placeholder ("Guest 4607") and set plan='lead'
    to satisfy NOT NULL schemas and mark as lead.
    On conflict, only update name if a non-empty name is provided.
    Returns {id, name, wa_number}.
    """
    wa = normalize_wa(wa_number)
    last4 = wa[-4:] if wa else "0000"
    placeholder = f"Guest {last4}"
    sql = text("""
        INSERT INTO clients (name, wa_number, credits, plan)
        VALUES (COALESCE(NULLIF(:name, ''), :placeholder), :wa, 0, COALESCE(NULLIF(:plan, ''), 'lead'))
        ON CONFLICT (wa_number)
        DO UPDATE SET
            name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name)
        RETURNING id, name, wa_number
    """)
    with get_session() as s:
        row = s.execute(sql, {
            "name": (name or "").strip(),
            "placeholder": placeholder,
            "wa": wa,
            "plan": "lead",
        }).mappings().first()
        return dict(row)


def list_clients(limit: int = 10, offset: int = 0) -> List[Dict]:
    sql = text("""
        SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number,
               COALESCE(plan,'') AS plan, COALESCE(credits,0) AS credits
        FROM clients
        ORDER BY COALESCE(name,''), id
        LIMIT :lim OFFSET :off
    """)
    with get_session() as s:
        rows = s.execute(sql, {"lim": int(limit), "off": int(offset)}).mappings().all()
        return [dict(r) for r in rows]


def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Case-insensitive substring match on name.
    """
    q = (q or "").strip()
    if not q:
        return list_clients(limit=limit, offset=offset)
    sql = text("""
        SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number,
               COALESCE(plan,'') AS plan, COALESCE(credits,0) AS credits
        FROM clients
        WHERE LOWER(COALESCE(name,'')) LIKE LOWER(:needle)
        ORDER BY COALESCE(name,''), id
        LIMIT :lim OFFSET :off
    """)
    with get_session() as s:
        rows = s.execute(sql, {
            "needle": f"%{q}%",
            "lim": int(limit),
            "off": int(offset),
        }).mappings().all()
        return [dict(r) for r in rows]


def find_clients_by_prefix(q: str, limit: int = 10, offset: int = 0, min_len: int = 3) -> List[Dict]:
    """
    Prefix search used by admin quick search.
    - Requires at least `min_len` characters (defaults to 3).
    - Matches on name prefix OR normalized wa_number prefix (without +).
    """
    q = (q or "").strip()
    if len(q) < int(min_len):
        return []

    # Build two needles: for name and for wa_number (strip '+' for comparison)
    name_prefix = f"{q}%"
    wa_prefix = q.lstrip('+')
    wa_prefix_needle = f"{wa_prefix}%"

    sql = text("""
        SELECT id,
               COALESCE(name,'')      AS name,
               COALESCE(wa_number,'') AS wa_number,
               COALESCE(plan,'')      AS plan,
               COALESCE(credits,0)    AS credits
        FROM clients
        WHERE
            LOWER(COALESCE(name,'')) LIKE LOWER(:namepref)
            OR REPLACE(COALESCE(wa_number,''), '+', '') LIKE :wapref
        ORDER BY COALESCE(name,''), id
        LIMIT :lim OFFSET :off
    """)
    with get_session() as s:
        rows = s.execute(sql, {
            "namepref": name_prefix,
            "wapref": wa_prefix_needle,
            "lim": int(limit),
            "off": int(offset),
        }).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Booking helpers
# ──────────────────────────────────────────────────────────────────────────────

def find_next_upcoming_booking_by_wa(wa_number: str) -> Optional[Dict]:
    """
    Return the soonest future confirmed booking for this WA number (local SAST boundary).
    """
    wa = normalize_wa(wa_number)
    sql = text("""
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
    """)
    with get_session() as s:
        row = s.execute(sql, {"wa": wa}).mappings().first()
        return dict(row) if row else None


def client_upcoming_bookings(client_id: int, limit: int = 20) -> List[Dict]:
    """
    All upcoming confirmed bookings for a client (from 'now' in SAST), soonest first.
    Returns rows with: booking_id, session_id, session_date, start_time, status.
    """
    sql = text("""
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
        )
        SELECT
            b.id AS booking_id,
            s.id AS session_id,
            s.session_date,
            s.start_time,
            b.status
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        , now_local
        WHERE b.client_id = :cid
          AND b.status = 'confirmed'
          AND (s.session_date + s.start_time) >= now_local.ts
        ORDER BY s.session_date, s.start_time
        LIMIT :lim
    """)
    with get_session() as s:
        rows = s.execute(sql, {"cid": int(client_id), "lim": int(limit)}).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Admin inbox
# ──────────────────────────────────────────────────────────────────────────────

def inbox_upsert(
    *,
    kind: str,
    title: str,
    body: str,
    source: str = "system",       # 'whatsapp' | 'cron' | 'system'
    status: str = "open",         # 'open' | 'in_progress' | 'closed'
    is_unread: bool = True,
    action_required: bool = False,
    bucket: str | None = None,    # for dedupe (e.g., 'YYYY-MM-DD-HH' or date)
    session_id: int | None = None,
    client_id: int | None = None,
) -> Optional[int]:
    """
    Insert an admin_inbox row idempotently using a digest on (kind, title, body, bucket).
    Accepts alias 'daily' → 'recap' so older callers don't crash.
    """
    alias_map = {"daily": "recap"}
    kind = alias_map.get(kind, kind)

    allowed = {"booking_request", "query", "hourly", "recap", "system"}
    if kind not in allowed:
        raise ValueError(f"Unsupported inbox kind: {kind}")

    digest = sha256(f"{kind}|{title}|{body}|{bucket or ''}".encode("utf-8")).hexdigest()

    sql = text("""
        INSERT INTO admin_inbox
          (kind, title, body, session_id, client_id, source, status,
           is_unread, action_required, bucket, digest)
        VALUES
          (:k,   :t,    :b,   :sid,       :cid,       :src,   :st,
           :ur,      :ar,             :bk,    :dg)
        ON CONFLICT (digest) DO NOTHING
        RETURNING id
    """)
    with get_session() as s:
        row = s.execute(sql, {
            "k": kind, "t": title, "b": body,
            "sid": session_id, "cid": client_id,
            "src": source, "st": status,
            "ur": bool(is_unread), "ar": bool(action_required),
            "bk": bucket, "dg": digest,
        }).mappings().first()
        return (row or {}).get("id")
