# app/crud.py
from __future__ import annotations

from typing import List, Optional
from sqlalchemy import text

from .db import get_session


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
