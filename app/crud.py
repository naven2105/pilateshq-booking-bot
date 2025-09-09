# app/crud.py
from __future__ import annotations

from typing import List, Optional
from hashlib import sha256

from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa


# ──────────────────────────────────────────────────────────────────────────────
# Lead / client existence & upsert
# ──────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    """
    Returns True if a client row exists with the normalized WA number.
    """
    wa = normalize_wa(wa_number)
    if not wa:
        return False
    with get_session() as s:
        row = s.execute(
            text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"),
            {"wa": wa},
        ).first()
        return bool(row)


def upsert_public_client(wa_number: str, name: Optional[str]) -> dict:
    """
    Ensure a lead-style client exists.
    - Normalizes the WA number.
    - Sets a friendly default name if none provided (e.g., 'Guest 4607').
    - Uses plan='lead' and credits=0 to satisfy NOT NULL constraints.
    - On conflict, updates the name if we now have a non-empty one.
    Returns: {id, name, wa_number}
    """
    wa = normalize_wa(wa_number)
    if not wa:
        raise ValueError("Invalid WhatsApp number")

    safe_name = (name or "").strip()
    if not safe_name:
        # Make a simple placeholder like 'Guest 4607'
        tail4 = wa[-4:] if len(wa) >= 4 else wa
        safe_name = f"Guest {tail4}"

    with get_session() as s:
        row = s.execute(
            text(
                """
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (:name, :wa, 0, 'lead')
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name)
                RETURNING id, name, wa_number
                """
            ),
            {"name": safe_name, "wa": wa},
        ).mappings().first()
        return dict(row)


# ──────────────────────────────────────────────────────────────────────────────
# Admin inbox writer (idempotent)
# ──────────────────────────────────────────────────────────────────────────────

def inbox_upsert(
    *,
    kind: str,                # 'booking_request' | 'query' | 'hourly' | 'recap' | 'system'
    title: str,
    body: str,
    client_id: Optional[int] = None,
    session_id: Optional[int] = None,
    source: str = "system",   # 'whatsapp' | 'cron' | 'system'
    status: str = "open",     # 'open' | 'in_progress' | 'closed'
    is_unread: bool = True,
    action_required: bool = False,
    bucket: Optional[str] = None,   # for dedupe windows (e.g., hourly)
) -> Optional[int]:
    """
    Insert (or ignore) an admin_inbox row with a stable digest for idempotency.
    Returns the new id if inserted, else None if it already existed.
    NOTE: Your DB must include columns: is_unread, action_required, bucket, digest.
    """
    # Keep kind within your CHECK constraint set
    allowed_kinds = {"booking_request", "query", "hourly", "recap", "system"}
    if kind not in allowed_kinds:
        raise ValueError(f"Unsupported inbox kind: {kind}")

    # Build a deterministic digest over the salient fields
    dg_src = f"{kind}|{title}|{body}|{client_id or ''}|{session_id or ''}|{source}|{status}|{bucket or ''}"
    digest = sha256(dg_src.encode("utf-8")).hexdigest()

    with get_session() as s:
        row = s.execute(
            text(
                """
                INSERT INTO admin_inbox
                  (kind, title, body, session_id, client_id, source, status,
                   is_unread, action_required, bucket, digest)
                VALUES
                  (:k,   :t,    :b,   :sid,       :cid,       :src,   :st,
                   :iu,        :ar,             :bk,    :dg)
                ON CONFLICT (digest) DO NOTHING
                RETURNING id
                """
            ),
            {
                "k": kind,
                "t": title,
                "b": body,
                "sid": session_id,
                "cid": client_id,
                "src": source,
                "st": status,
                "iu": bool(is_unread),
                "ar": bool(action_required),
                "bk": bucket,
                "dg": digest,
            },
        ).mappings().first()
        return (row and row["id"]) or None


# ──────────────────────────────────────────────────────────────────────────────
# Client search helpers
# ──────────────────────────────────────────────────────────────────────────────

def find_clients_by_prefix(prefix: str, limit: int = 10, offset: int = 0) -> List[dict]:
    """
    Search clients by:
      - Name prefix (case-insensitive)
      - OR WA number prefix (digits-only, '+' ignored)
    Returns: id, name, wa_number, plan, credits
    """
    q = (prefix or "").strip()
    if not q:
        return []

    with get_session() as s:
        rows = s.execute(
            text(
                """
                SELECT
                    id,
                    COALESCE(name, '')      AS name,
                    COALESCE(wa_number, '') AS wa_number,
                    COALESCE(plan, '')      AS plan,
                    COALESCE(credits, 0)    AS credits
                FROM clients
                WHERE
                    LOWER(COALESCE(name, '')) LIKE LOWER(:namepref)
                    OR REPLACE(COALESCE(wa_number, ''), '+', '') LIKE :wapref
                ORDER BY COALESCE(name, ''), id
                LIMIT :lim OFFSET :off
                """
            ),
            {
                "namepref": f"{q}%",
                "wapref": f"{q.lstrip('+')}%",
                "lim": int(limit),
                "off": int(offset),
            },
        ).mappings().all()
        return [dict(r) for r in rows]


def find_one_client(query: str) -> Optional[dict]:
    """
    Resolve a single client by:
      • '#<id>' exact id
      • WA number (exact or prefix, + ignored)
      • Name (exact/starts-with/contains; pick best match)
    Returns: id, name, wa_number, plan, credits
    """
    q = (query or "").strip()
    if not q:
        return None

    with get_session() as s:
        # Case 1: #<id>
        if q.startswith("#") and q[1:].isdigit():
            row = s.execute(
                text(
                    """
                    SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number,
                           COALESCE(plan,'') AS plan, COALESCE(credits,0) AS credits
                    FROM clients
                    WHERE id = :id
                    """
                ),
                {"id": int(q[1:])},
            ).mappings().first()
            return dict(row) if row else None

        # Case 2: WA number-ish (mostly digits / +)
        if q.replace("+", "").isdigit():
            row = s.execute(
                text(
                    """
                    SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number,
                           COALESCE(plan,'') AS plan, COALESCE(credits,0) AS credits
                    FROM clients
                    WHERE REPLACE(COALESCE(wa_number,''), '+', '') LIKE :wapref
                    ORDER BY length(REPLACE(COALESCE(wa_number,''), '+', '')) ASC, id
                    LIMIT 1
                    """
                ),
                {"wapref": f"{q.lstrip('+')}%"},
            ).mappings().first()
            return dict(row) if row else None

        # Case 3: name
        # Prefer exact (case-insensitive), then starts-with, then contains
        row = s.execute(
            text(
                """
                WITH base AS (
                    SELECT id,
                           COALESCE(name,'')      AS name,
                           COALESCE(wa_number,'') AS wa_number,
                           COALESCE(plan,'')      AS plan,
                           COALESCE(credits,0)    AS credits
                    FROM clients
                ),
                ranked AS (
                    SELECT *,
                        CASE
                          WHEN LOWER(name) = LOWER(:q) THEN 1
                          WHEN LOWER(name) LIKE LOWER(:qsw) THEN 2
                          WHEN LOWER(name) LIKE LOWER(:qct) THEN 3
                          ELSE 9
                        END AS rank_key
                    FROM base
                )
                SELECT * FROM ranked
                WHERE rank_key < 9
                ORDER BY rank_key, name, id
                LIMIT 1
                """
            ),
            {"q": q, "qsw": f"{q}%", "qct": f"%{q}%"},
        ).mappings().first()
        return dict(row) if row else None


# ──────────────────────────────────────────────────────────────────────────────
# Client profile data
# ──────────────────────────────────────────────────────────────────────────────

def client_upcoming_bookings(client_id: int, limit: int = 6) -> List[dict]:
    """
    Next up to N bookings (today onward) in local SA time.
    Returns rows with local_dt (YYYY-MM-DD HH:MM) and status.
    """
    with get_session() as s:
        rows = s.execute(
            text(
                """
                WITH now_local AS (
                  SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
                ),
                fut AS (
                  SELECT b.status,
                         to_char((s.session_date + s.start_time), 'YYYY-MM-DD HH24:MI') AS local_dt
                  FROM bookings b
                  JOIN sessions s ON s.id = b.session_id
                  , now_local
                  WHERE b.client_id = :cid
                    AND (s.session_date + s.start_time) >= now_local.ts
                  ORDER BY s.session_date, s.start_time
                  LIMIT :lim
                )
                SELECT * FROM fut
                """
            ),
            {"cid": int(client_id), "lim": int(limit)},
        ).mappings().all()
        return [dict(r) for r in rows]


def client_recent_history(client_id: int, limit: int = 3) -> List[dict]:
    """
    Last N historical bookings (most recent first).
    Returns rows with local_dt and status.
    """
    with get_session() as s:
        rows = s.execute(
            text(
                """
                WITH now_local AS (
                  SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
                ),
                hist AS (
                  SELECT b.status,
                         to_char((s.session_date + s.start_time), 'YYYY-MM-DD HH24:MI') AS local_dt
                  FROM bookings b
                  JOIN sessions s ON s.id = b.session_id
                  , now_local
                  WHERE b.client_id = :cid
                    AND (s.session_date + s.start_time) < now_local.ts
                  ORDER BY s.session_date DESC, s.start_time DESC
                  LIMIT :lim
                )
                SELECT * FROM hist
                """
            ),
            {"cid": int(client_id), "lim": int(limit)},
        ).mappings().all()
        return [dict(r) for r in rows]
