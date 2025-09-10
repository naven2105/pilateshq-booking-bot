# app/crud.py
from __future__ import annotations

import hashlib
from typing import Optional, List, Dict

from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa


# ─────────────────────────────────────────────────────────────────────────────
# Leads / Clients
# ─────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(
            text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"),
            {"wa": wa if wa.startswith("+") else f"+{wa}"}
        ).first()
        return row is not None


def upsert_public_client(wa_number: str, name: Optional[str]) -> dict:
    """
    Ensure a lead/client exists. If name is provided (non-empty), set/keep it.
    Uses plan NULL or default if your schema requires NOT NULL for plan, adjust below.
    """
    wa_norm = normalize_wa(wa_number)
    nm = (name or "").strip()

    # If your clients.plan is NOT NULL, you can default it here instead of NULL.
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (COALESCE(NULLIF(:name,''), CONCAT('Guest ', RIGHT(:wan, 4))), :wan, 0, COALESCE(NULL, plan) )
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name,''), clients.name)
                RETURNING id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number
            """),
            {"name": nm, "wan": wa_norm if wa_norm.startswith("+") else f"+{wa_norm}"},
        ).mappings().first()
        return dict(row)


def find_clients_by_prefix(prefix: str, limit: int = 10) -> List[dict]:
    p = (prefix or "").strip()
    if not p:
        return []
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number
                FROM clients
                WHERE LOWER(COALESCE(name,'')) LIKE LOWER(:pfx) || '%'
                ORDER BY COALESCE(name,''), id
                LIMIT :lim
            """),
            {"pfx": p, "lim": int(limit)},
        ).mappings().all()
        return [dict(r) for r in rows]


def list_clients(limit: int = 10, offset: int = 0) -> List[dict]:
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number
                FROM clients
                ORDER BY COALESCE(name,''), id
                LIMIT :lim OFFSET :off
            """),
            {"lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]


def find_one_client(q: str):
    """
    Best-effort resolver:
      - If q is numeric => treat as ID
      - Else if q looks like a phone => normalize and match wa_number
      - Else => name prefix search
    Returns:
      - dict(client) if exactly one match
      - {"_multi": [clients...]} if multiple
      - None if none
    """
    q = (q or "").strip()
    if not q:
        return None

    # ID path
    if q.isdigit():
        with get_session() as s:
            row = s.execute(
                text("""
                    SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number
                    FROM clients WHERE id = :cid
                """),
                {"cid": int(q)},
            ).mappings().first()
            return dict(row) if row else None

    # Phone path
    wa_norm = normalize_wa(q)
    if wa_norm:
        with get_session() as s:
            rows = s.execute(
                text("""
                    SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number
                    FROM clients
                    WHERE wa_number IN (:w_plus, :w_raw)
                """),
                {
                    "w_plus": wa_norm if wa_norm.startswith("+") else f"+{wa_norm}",
                    "w_raw": wa_norm,
                },
            ).mappings().all()
            if len(rows) == 1:
                return dict(rows[0])
            if len(rows) > 1:
                return {"_multi": [dict(r) for r in rows]}

    # Name prefix
    matches = find_clients_by_prefix(q, limit=10)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return {"_multi": matches}
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Sessions with Names (used by admin/tasks)
# ─────────────────────────────────────────────────────────────────────────────

def sessions_today_with_names(tz_name: str, upcoming_only: bool = True) -> List[dict]:
    """
    Returns today's sessions (optionally upcoming only) with aggregated confirmed client names.
    """
    sql = f"""
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        pool AS (
            SELECT s.id, s.session_date, s.start_time, s.capacity,
                   s.booked_count, s.status, COALESCE(s.notes,'') AS notes
            FROM sessions s, now_local
            WHERE s.session_date = (now_local.ts)::date
            {"AND s.start_time >= (now_local.ts)::time" if upcoming_only else ""}
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
    """
    with get_session() as s:
        rows = s.execute(text(sql), {"tz": tz_name}).mappings().all()
        return [dict(r) for r in rows]


def sessions_next_hour_with_names(tz_name: str) -> List[dict]:
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        bounds AS (
            SELECT date_trunc('hour', ts) AS h, date_trunc('hour', ts) + INTERVAL '1 hour' AS h_plus
            FROM now_local
        )
        SELECT
            s.id, s.session_date, s.start_time, s.capacity, s.booked_count, s.status, COALESCE(s.notes,'') AS notes,
            COALESCE((
                SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                FROM (
                    SELECT DISTINCT COALESCE(c2.name, '') AS nm
                    FROM bookings b2
                    JOIN clients  c2 ON c2.id = b2.client_id
                    WHERE b2.session_id = s.id AND b2.status = 'confirmed'
                ) d
            ), '') AS names
        FROM sessions s, bounds
        WHERE (s.session_date + s.start_time) >= bounds.h
          AND (s.session_date + s.start_time) <  bounds.h_plus
        ORDER BY s.start_time
    """
    with get_session() as s:
        rows = s.execute(text(sql), {"tz": tz_name}).mappings().all()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Client activity (optional helpers)
# ─────────────────────────────────────────────────────────────────────────────

def client_upcoming_bookings(client_id: int, tz_name: str) -> List[dict]:
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                )
                SELECT s.session_date, s.start_time, b.status
                FROM bookings b
                JOIN sessions s ON s.id = b.session_id
                , now_local
                WHERE b.client_id = :cid
                  AND (s.session_date + s.start_time) >= now_local.ts
                ORDER BY s.session_date, s.start_time
            """),
            {"cid": int(client_id), "tz": tz_name},
        ).mappings().all()
        return [dict(r) for r in rows]


def client_recent_history(client_id: int, limit: int = 10) -> List[dict]:
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT s.session_date, s.start_time, b.status
                FROM bookings b
                JOIN sessions s ON s.id = b.session_id
                WHERE b.client_id = :cid
                ORDER BY s.session_date DESC, s.start_time DESC
                LIMIT :lim
            """),
            {"cid": int(client_id), "lim": int(limit)},
        ).mappings().all()
        return [dict(r) for r in rows]


def find_next_upcoming_booking_by_wa(wa_number: str) -> Optional[dict]:
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
            WHERE c.wa_number IN (:wa_plus, :wa_raw)
              AND b.status = 'confirmed'
              AND (s.session_date + s.start_time) > now_local.ts
            ORDER BY s.session_date, s.start_time
            LIMIT 1
        """), {"wa_plus": wa if wa.startswith("+") else f"+{wa}", "wa_raw": wa}).mappings().first()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Admin Inbox
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_INBOX_KINDS = {"hourly", "recap", "booking_request", "query", "system", "daily"}  # allow 'daily' too


def inbox_upsert(
    *,
    kind: str,
    title: str,
    body: str,
    session_id: Optional[int] = None,
    client_id: Optional[int] = None,
    source: str = "system",
    status: str = "open",
    is_unread: bool = True,
    action_required: bool = False,
    bucket: Optional[str] = None,
    digest: Optional[str] = None,
) -> Optional[int]:
    """
    Insert an inbox row idempotently (by digest). If digest not provided, derive from fields.
    """
    if kind not in _ALLOWED_INBOX_KINDS:
        raise ValueError(f"Unsupported inbox kind: {kind}")

    if not digest:
        h = hashlib.sha256()
        h.update((kind or "").encode())
        h.update((title or "").encode())
        h.update((body or "").encode())
        h.update((bucket or "").encode())
        if session_id:
            h.update(f"sid:{session_id}".encode())
        if client_id:
            h.update(f"cid:{client_id}".encode())
        digest = h.hexdigest()

    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO admin_inbox
                  (kind, title, body, session_id, client_id, source, status, is_unread, action_required, bucket, digest)
                VALUES
                  (:k,   :t,    :b,   :sid,       :cid,       :src,   :st,       :iu,       :ar,              :bk,    :dg)
                ON CONFLICT (digest) DO NOTHING
                RETURNING id
            """),
            {"k": kind, "t": title, "b": body, "sid": session_id, "cid": client_id,
             "src": source, "st": status, "iu": bool(is_unread), "ar": bool(action_required),
             "bk": bucket, "dg": digest},
        ).mappings().first()
        return (row or {}).get("id")


def inbox_counts() -> dict:
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT
                  SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END)::int AS open_count,
                  SUM(CASE WHEN is_unread THEN 1 ELSE 0 END)::int       AS unread_count,
                  SUM(CASE WHEN action_required THEN 1 ELSE 0 END)::int AS action_count
                FROM admin_inbox
            """)
        ).mappings().first()
        return dict(row) if row else {"open_count": 0, "unread_count": 0, "action_count": 0}


def inbox_recent(kind: Optional[str] = None, limit: int = 5) -> List[dict]:
    with get_session() as s:
        if kind:
            rows = s.execute(
                text("""
                    SELECT id, kind, title, body, status, is_unread, action_required, created_at
                    FROM admin_inbox
                    WHERE kind = :k
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"k": kind, "lim": int(limit)},
            ).mappings().all()
        else:
            rows = s.execute(
                text("""
                    SELECT id, kind, title, body, status, is_unread, action_required, created_at
                    FROM admin_inbox
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"lim": int(limit)},
            ).mappings().all()
        return [dict(r) for r in rows]


def inbox_mark_read(inbox_id: int) -> None:
    with get_session() as s:
        s.execute(
            text("UPDATE admin_inbox SET is_unread = FALSE WHERE id = :iid"),
            {"iid": int(inbox_id)},
        )
