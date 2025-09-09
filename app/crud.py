# app/crud.py
from __future__ import annotations

from typing import Optional, Dict, List
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa


# ──────────────────────────────────────────────────────────────────────────────
# Clients
# ──────────────────────────────────────────────────────────────────────────────

def find_client_by_wa(wa_number: str) -> Optional[Dict]:
    """Return client row by WhatsApp number (normalized), or None."""
    wa = normalize_wa(wa_number)
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


def client_exists_by_wa(wa_number: str) -> bool:
    """True if a client with this WA exists."""
    return find_client_by_wa(wa_number) is not None


def upsert_public_client(wa_number: str, name: Optional[str]) -> Dict:
    """
    Ensure a lightweight client record exists for a public lead.
    - Normalizes WA
    - Inserts with plan='lead', credits=0
    - If already exists, keeps existing name unless a new non-empty name is provided.
    Returns {id, name, wa_number}.
    """
    wa = normalize_wa(wa_number)
    if not wa:
        raise ValueError("Invalid WA number")

    safe_name = (name or "").strip()
    # If name empty, use a friendly “Guest ####” placeholder
    placeholder = f"Guest {wa[-4:]}"  # last 4 digits

    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (COALESCE(NULLIF(:name, ''), :placeholder), :wa, 0, 'lead')
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name)
                RETURNING id, name, wa_number
            """),
            {"name": safe_name, "placeholder": placeholder, "wa": wa},
        ).mappings().first()
        return dict(row)


# Basic list/search used by admin pickers

def list_clients(limit: int = 10, offset: int = 0) -> List[Dict]:
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT id,
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


def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> List[Dict]:
    q = (q or "").strip()
    if not q:
        return list_clients(limit=limit, offset=offset)
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT id,
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


# ──────────────────────────────────────────────────────────────────────────────
# Sessions / Bookings (used in admin summaries, etc.)
# ──────────────────────────────────────────────────────────────────────────────

def sessions_today_with_names(tz_name: str, upcoming_only: bool) -> List[Dict]:
    """
    Return today's sessions in local tz, with a comma-separated names string
    of confirmed attendees ('' if none).
    """
    with get_session() as s:
        sql = text(f"""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            ),
            base AS (
                SELECT s.id, s.session_date, s.start_time, s.capacity,
                       s.booked_count, s.status, COALESCE(s.notes,'') AS notes
                FROM sessions s, now_local
                WHERE s.session_date = (now_local.ts)::date
                  {'AND s.start_time >= (now_local.ts)::time' if upcoming_only else ''}
            )
            SELECT
                b.*,
                COALESCE((
                    SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                    FROM (
                        SELECT DISTINCT COALESCE(c2.name,'') AS nm
                        FROM bookings b2
                        JOIN clients  c2 ON c2.id = b2.client_id
                        WHERE b2.session_id = b.id
                          AND b2.status = 'confirmed'
                    ) d
                ), '') AS names
            FROM base b
            ORDER BY b.start_time
        """)
        rows = s.execute(sql, {"tz": tz_name}).mappings().all()
        return [dict(r) for r in rows]


def sessions_next_hour_with_names(tz_name: str) -> List[Dict]:
    with get_session() as s:
        sql = text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            ),
            win AS (
                SELECT ts, (ts + INTERVAL '1 hour') AS ts_plus FROM now_local
            )
            SELECT
                s.id, s.session_date, s.start_time, s.capacity,
                s.booked_count, s.status, COALESCE(s.notes,'') AS notes,
                COALESCE((
                    SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                    FROM (
                        SELECT DISTINCT COALESCE(c2.name,'') AS nm
                        FROM bookings b2
                        JOIN clients  c2 ON c2.id = b2.client_id
                        WHERE b2.session_id = s.id
                          AND b2.status = 'confirmed'
                    ) d
                ), '') AS names
            FROM sessions s
            CROSS JOIN win
            WHERE (s.session_date + s.start_time) >= win.ts
              AND (s.session_date + s.start_time) <  win.ts_plus
            ORDER BY s.start_time
        """)
        rows = s.execute(sql, {"tz": tz_name}).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Admin Inbox
# ──────────────────────────────────────────────────────────────────────────────

def inbox_upsert(
    *,
    kind: str,             # 'booking_request' | 'query' | 'hourly' | 'recap' | 'system'
    title: str,
    body: str,
    session_id: Optional[int] = None,
    client_id: Optional[int] = None,
    source: str = "system", # 'whatsapp' | 'cron' | 'system'
    status: str = "open",   # 'open' | 'in_progress' | 'closed'
    is_unread: bool = True,
    action_required: bool = False,
    bucket: Optional[str] = None,
    digest: Optional[str] = None,
) -> Optional[int]:
    """
    Insert an inbox row with idempotency on (digest).
    Returns inserted id or None if skipped by ON CONFLICT.
    """
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO admin_inbox
                  (kind, title, body, session_id, client_id, source, status, is_unread, action_required, bucket, digest)
                VALUES
                  (:k,   :t,    :b,   :sid,       :cid,       :src,   :st,      :iu,       :ar,              :bk,    :dg)
                ON CONFLICT (digest) DO NOTHING
                RETURNING id
            """),
            {
                "k": kind, "t": title, "b": body,
                "sid": session_id, "cid": client_id,
                "src": source, "st": status,
                "iu": bool(is_unread), "ar": bool(action_required),
                "bk": bucket, "dg": digest,
            },
        ).mappings().first()
        return (row or {}).get("id")


def inbox_counts() -> Dict[str, int]:
    """Return counts used for admin header badges."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT
                  SUM(CASE WHEN is_unread THEN 1 ELSE 0 END)      AS unread,
                  SUM(CASE WHEN action_required THEN 1 ELSE 0 END) AS action_required
                FROM admin_inbox
            """)
        ).mappings().first() or {}
        return {
            "unread": int(row.get("unread") or 0),
            "action_required": int(row.get("action_required") or 0),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Lead “expectation” helpers (graceful if table doesn’t exist yet)
# ──────────────────────────────────────────────────────────────────────────────

def lead_set_expectation(wa_number: str, expecting: str, payload: Optional[str] = None) -> None:
    """
    Store a one-step expectation for a lead (e.g., next input should be their name).
    If the table doesn't exist yet, this will no-op.
    """
    try:
        with get_session() as s:
            s.execute(
                text("""
                    INSERT INTO lead_expectations (wa_number, expecting, payload, created_at)
                    VALUES (:wa, :exp, :pay, now())
                    ON CONFLICT (wa_number)
                    DO UPDATE SET expecting = EXCLUDED.expecting,
                                  payload   = EXCLUDED.payload,
                                  created_at = now()
                """),
                {"wa": normalize_wa(wa_number), "exp": expecting, "pay": payload},
            )
    except Exception:
        # Table may not exist yet; ignore to keep flow running.
        pass


def lead_peek_expectation(wa_number: str) -> Optional[Dict]:
    """Return current expectation row without clearing it (or None)."""
    try:
        with get_session() as s:
            row = s.execute(
                text("""
                    SELECT wa_number, expecting, payload, created_at
                    FROM lead_expectations
                    WHERE wa_number = :wa
                    LIMIT 1
                """),
                {"wa": normalize_wa(wa_number)},
            ).mappings().first()
            return dict(row) if row else None
    except Exception:
        return None


def lead_pop_expectation(wa_number: str) -> Optional[Dict]:
    """Fetch & clear the expectation atomically (or None)."""
    try:
        with get_session() as s:
            row = s.execute(
                text("""
                    DELETE FROM lead_expectations
                    WHERE wa_number = :wa
                    RETURNING wa_number, expecting, payload, created_at
                """),
                {"wa": normalize_wa(wa_number)},
            ).mappings().first()
            return dict(row) if row else None
    except Exception:
        return None
