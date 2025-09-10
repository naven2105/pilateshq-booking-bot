# app/crud.py
from __future__ import annotations

import hashlib
from typing import Optional, List, Dict

from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa
from .config import TZ_NAME


# ──────────────────────────────────────────────────────────────────────────────
# Clients
# ──────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    """
    True if a client row exists for this WhatsApp number.
    We check both '2773…' and '+2773…' forms to be robust.
    """
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT 1
                FROM clients
                WHERE wa_number IN (:wa, '+' || :wa)
                LIMIT 1
            """),
            {"wa": wa},
        ).first()
        return bool(row)


def upsert_public_client(wa_number: str, name: Optional[str]) -> Dict:
    """
    Ensure a 'lead' client exists. Will not overwrite an existing name with empty.
    Uses plan='lead' as a safe non-null default.
    """
    wa = normalize_wa(wa_number)
    # Fallback name if none was provided
    fallback = None
    if not name or not name.strip():
        # e.g. 'Guest 4607' from the last 4 digits
        tail = wa[-4:] if wa else "0000"
        fallback = f"Guest {tail}"

    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (COALESCE(NULLIF(:nm, ''), :fallback), :wa, 0, 'lead')
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name)
                RETURNING id, name, wa_number
            """),
            {"nm": (name or "").strip(), "fallback": fallback, "wa": wa},
        ).mappings().first()
        return dict(row) if row else {}


def find_clients_by_prefix(prefix: str, limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Case-insensitive prefix search on name OR on wa_number (prefix).
    """
    q = (prefix or "").strip()
    if not q:
        return []

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
                WHERE
                    LOWER(COALESCE(name, '')) LIKE LOWER(:name_pref)
                    OR REPLACE(wa_number, '+', '') LIKE REPLACE(:wa_pref, '+', '')
                ORDER BY COALESCE(name, ''), id
                LIMIT :lim OFFSET :off
            """),
            {"name_pref": f"{q}%", "wa_pref": f"{q}%", "lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


def find_one_client(identifier: str) -> Optional[Dict]:
    """
    Flexible fetch:
      - If numeric => treat as client id
      - Else, try by exact wa_number (normalized), then by exact name (case-insensitive)
    Returns minimal fields.
    """
    ident = (identifier or "").strip()
    if not ident:
        return None

    with get_session() as s:
        # Try by integer id
        try:
            cid = int(ident)
            row = s.execute(
                text("""
                    SELECT id, name, wa_number, COALESCE(credits,0) AS credits, COALESCE(plan,'') AS plan
                    FROM clients
                    WHERE id = :cid
                    LIMIT 1
                """),
                {"cid": cid},
            ).mappings().first()
            if row:
                return dict(row)
        except ValueError:
            pass

        # Try by WA
        wa = normalize_wa(ident)
        row = s.execute(
            text("""
                SELECT id, name, wa_number, COALESCE(credits,0) AS credits, COALESCE(plan,'') AS plan
                FROM clients
                WHERE wa_number IN (:wa, '+' || :wa)
                LIMIT 1
            """),
            {"wa": wa},
        ).mappings().first()
        if row:
            return dict(row)

        # Try by exact name (case-insensitive)
        row = s.execute(
            text("""
                SELECT id, name, wa_number, COALESCE(credits,0) AS credits, COALESCE(plan,'') AS plan
                FROM clients
                WHERE LOWER(COALESCE(name,'')) = LOWER(:nm)
                ORDER BY id
                LIMIT 1
            """),
            {"nm": ident},
        ).mappings().first()
        return dict(row) if row else None


# Optional helpers (not currently used by the simplified admin, but harmless)
def client_upcoming_bookings(client_id: int, limit: int = 10) -> List[Dict]:
    """
    Upcoming confirmed bookings for a client.
    """
    with get_session() as s:
        rows = s.execute(
            text(f"""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
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
            """),
            {"cid": int(client_id), "lim": int(limit), "tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


def client_recent_history(client_id: int, limit: int = 10) -> List[Dict]:
    """
    Most recent bookings (any status) for a client, newest first.
    """
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                    b.id AS booking_id,
                    s.id AS session_id,
                    s.session_date,
                    s.start_time,
                    b.status
                FROM bookings b
                JOIN sessions s ON s.id = b.session_id
                WHERE b.client_id = :cid
                ORDER BY s.session_date DESC, s.start_time DESC
                LIMIT :lim
            """),
            {"cid": int(client_id), "lim": int(limit)},
        ).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Sessions (names aggregated)
# ──────────────────────────────────────────────────────────────────────────────

def sessions_today_names() -> List[Dict]:
    """
    Return today's sessions (full day) with aggregated DISTINCT confirmed client names.
    """
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                ),
                pool AS (
                    SELECT s.id, s.session_date, s.start_time, s.capacity,
                           s.booked_count, s.status, COALESCE(s.notes,'') AS notes
                    FROM sessions s, now_local
                    WHERE s.session_date = (now_local.ts)::date
                )
                SELECT
                    p.*,
                    COALESCE((
                        SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                        FROM (
                            SELECT DISTINCT COALESCE(c2.name, '') AS nm
                            FROM bookings b2
                            JOIN clients  c2 ON c2.id = b2.client_id
                            WHERE b2.session_id = p.id AND b2.status = 'confirmed'
                        ) d
                    ), '') AS names
                FROM pool p
                ORDER BY p.session_date, p.start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Admin Inbox
# ──────────────────────────────────────────────────────────────────────────────

_ALLOWED_KINDS = {"booking_request", "query", "hourly", "recap", "system"}

def inbox_upsert(*,
                 kind: str,
                 title: str,
                 body: str,
                 source: str = "system",
                 status: str = "open",
                 is_unread: bool = True,
                 action_required: bool = False,
                 bucket: Optional[str] = None,
                 digest: Optional[str] = None,
                 session_id: Optional[int] = None,
                 client_id: Optional[int] = None) -> Optional[int]:
    """
    Insert an admin_inbox row idempotently via digest.
    Allowed kinds: booking_request | query | hourly | recap | system
    """
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Unsupported inbox kind: {kind}")

    if not digest:
        # Stable hash over main fields (bucket participates if present)
        base = f"{kind}|{title}|{body}|{source}|{status}|{bucket or ''}|{session_id or ''}|{client_id or ''}"
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()

    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO admin_inbox
                  (kind, title, body, session_id, client_id, source, status, is_unread, action_required, bucket, digest)
                VALUES
                  (:k,   :t,    :b,   :sid,       :cid,       :src,   :st,       :ur,       :ar,             :bk,    :dg)
                ON CONFLICT (digest) DO NOTHING
                RETURNING id
            """),
            {
                "k": kind, "t": title, "b": body,
                "sid": session_id, "cid": client_id,
                "src": source, "st": status,
                "ur": bool(is_unread), "ar": bool(action_required),
                "bk": bucket, "dg": digest
            },
        ).mappings().first()
        return int(row["id"]) if row and "id" in row else None


def inbox_counts() -> Dict[str, int]:
    """
    Quick counts for Admin home.
    """
    with get_session() as s:
        unread = s.execute(
            text("SELECT COUNT(*) AS n FROM admin_inbox WHERE is_unread = TRUE")
        ).mappings().first()["n"]

        open_ = s.execute(
            text("SELECT COUNT(*) AS n FROM admin_inbox WHERE status = 'open'")
        ).mappings().first()["n"]

        action = s.execute(
            text("SELECT COUNT(*) AS n FROM admin_inbox WHERE action_required = TRUE AND status <> 'closed'")
        ).mappings().first()["n"]

    return {"unread": int(unread or 0), "open": int(open_ or 0), "action": int(action or 0)}
