# app/crud.py
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import text

# ───────────────── Clients ─────────────────

def list_clients(limit: int = 20) -> List[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name, plan, credits
            FROM clients
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT :lim
        """), {"lim": limit}).mappings().all()
        return [dict(r) for r in rows]

def find_clients_by_name(name: str, limit: int = 6) -> List[Dict[str, Any]]:
    from .db import get_session
    q = f"%{name.strip()}%"
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name, plan, credits
            FROM clients
            WHERE name ILIKE :q
            ORDER BY name ASC
            LIMIT :lim
        """), {"q": q, "lim": limit}).mappings().all()
        return [dict(r) for r in rows]

def get_client_profile(client_id: int) -> Optional[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan, birthday_day, birthday_month, medical_notes, notes,
                   household_id, created_at, credits
            FROM clients WHERE id = :cid
        """), {"cid": client_id}).mappings().first()
        return dict(r) if r else None

def get_client_by_wa(wa_number: str) -> Optional[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan, birthday_day, birthday_month, medical_notes, notes,
                   household_id, created_at, credits
            FROM clients WHERE wa_number = :wa
            LIMIT 1
        """), {"wa": wa_number}).mappings().first()
        return dict(r) if r else None

def create_client(name: str, raw_phone: str) -> Optional[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        s.execute(text("""
            INSERT INTO clients (wa_number, name)
            VALUES (:wa, :nm)
            ON CONFLICT (wa_number) DO UPDATE SET name = EXCLUDED.name
        """), {"wa": raw_phone, "nm": name[:120]})
        r = s.execute(text("""
            SELECT id, wa_number, name, plan, credits
            FROM clients WHERE wa_number = :wa
        """), {"wa": raw_phone}).mappings().first()
        return dict(r) if r else None

def get_or_create_client(wa_number: str) -> Dict[str, Any]:
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, wa_number, name, plan, credits
            FROM clients WHERE wa_number = :wa
        """), {"wa": wa_number}).mappings().first()
        if r:
            return dict(r)
        s.execute(text("""
            INSERT INTO clients (wa_number, name)
            VALUES (:wa, '(new)')
            ON CONFLICT (wa_number) DO NOTHING
        """), {"wa": wa_number})
        r = s.execute(text("""
            SELECT id, wa_number, name, plan, credits
            FROM clients WHERE wa_number = :wa
        """), {"wa": wa_number}).mappings().first()
        return dict(r)

def update_client_dob(client_id: int, day: int, month: int) -> bool:
    from .db import get_session
    with get_session() as s:
        s.execute(text("""
            UPDATE clients
               SET birthday_day = :d, birthday_month = :m
             WHERE id = :cid
        """), {"d": day, "m": month, "cid": client_id})
        return True

def update_client_medical(client_id: int, note: str, append: bool = True) -> bool:
    from .db import get_session
    with get_session() as s:
        if append:
            s.execute(text("""
                UPDATE clients
                   SET medical_notes = trim(BOTH FROM
                       COALESCE(NULLIF(medical_notes,''),'') ||
                       CASE WHEN medical_notes IS NULL OR medical_notes = '' THEN '' ELSE E'\n' END ||
                       :note)
                 WHERE id = :cid
            """), {"note": note[:500], "cid": client_id})
        else:
            s.execute(text("UPDATE clients SET medical_notes = :note WHERE id = :cid"),
                      {"note": note[:500], "cid": client_id})
        return True

def adjust_client_credits(client_id: int, delta: int) -> None:
    from .db import get_session
    with get_session() as s:
        s.execute(text(
            "UPDATE clients SET credits = GREATEST(0, COALESCE(credits,0) + :d) WHERE id = :cid"
        ), {"d": delta, "cid": client_id})

def list_all_client_numbers() -> List[str]:
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT wa_number
            FROM clients
            WHERE COALESCE(NULLIF(wa_number,''),'') <> ''
        """)).all()
        return [r[0] for r in rows]

# ───────────────── Sessions / Bookings ─────────────────

def _ts_expr() -> str:
    # Postgres: combine to a comparable timestamp
    return "(session_date::timestamp + start_time)"

def sessions_next_hour() -> List[Dict[str, Any]]:
    """Sessions starting in the next clock hour. Excludes cancelled."""
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text(f"""
            WITH bounds AS (
              SELECT date_trunc('hour', now()) + interval '1 hour' AS start_ts,
                     date_trunc('hour', now()) + interval '2 hour' AS end_ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
              FROM sessions, bounds
             WHERE {_ts_expr()} >= bounds.start_ts
               AND {_ts_expr()} <  bounds.end_ts
               AND status <> 'cancelled'
             ORDER BY session_date, start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def sessions_tomorrow() -> List[Dict[str, Any]]:
    """All sessions tomorrow, excluding cancelled."""
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
              FROM sessions
             WHERE session_date = CURRENT_DATE + INTERVAL '1 day'
               AND status <> 'cancelled'
             ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def sessions_for_day(d: date, include_cancelled: bool = False) -> List[Dict[str, Any]]:
    """All sessions for a date; optionally include cancelled."""
    from .db import get_session
    with get_session() as s:
        if include_cancelled:
            q = """
                SELECT id, session_date, start_time, capacity, booked_count, status, notes
                  FROM sessions
                 WHERE session_date = :d
                 ORDER BY start_time
            """
        else:
            q = """
                SELECT id, session_date, start_time, capacity, booked_count, status, notes
                  FROM sessions
                 WHERE session_date = :d
                   AND status <> 'cancelled'
                 ORDER BY start_time
            """
        rows = s.execute(text(q), {"d": d}).mappings().all()
        return [dict(r) for r in rows]

def clients_for_session(session_id: int) -> List[Dict[str, Any]]:
    """Clients with active/confirmed bookings for a session (used for reminders)."""
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.id, c.name, c.wa_number
              FROM bookings b
              JOIN clients  c ON c.id = b.client_id
             WHERE b.session_id = :sid
               AND COALESCE(NULLIF(c.wa_number,''),'') <> ''
               AND (b.status IS NULL OR b.status IN ('confirmed','booked'))
        """), {"sid": session_id}).mappings().all()
        return [dict(r) for r in rows]

def find_session_by_date_time(d: date, hhmm: str) -> Optional[Dict[str, Any]]:
    """Lookup by date + HH:MM (excludes cancelled)."""
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
              FROM sessions
             WHERE session_date = :d
               AND start_time = :t::time
               AND status <> 'cancelled'
             LIMIT 1
        """), {"d": d, "t": hhmm}).mappings().first()
        return dict(r) if r else None

def cancel_next_booking_for_client(client_id: int) -> bool:
    """Cancel client’s next upcoming booking."""
    from .db import get_session
    with get_session() as s:
        r = s.execute(text(f"""
            WITH nextb AS (
              SELECT b.id
                FROM bookings b
                JOIN sessions s ON s.id = b.session_id
               WHERE b.client_id = :cid
                 AND (b.status IS NULL OR b.status IN ('booked','confirmed'))
                 AND {_ts_expr()} > now()
               ORDER BY s.session_date, s.start_time
               LIMIT 1
            )
            UPDATE bookings b
               SET status = 'cancelled'
              FROM nextb
             WHERE b.id = nextb.id
            RETURNING b.id
        """), {"cid": client_id}).first()
        return bool(r)

def mark_no_show_today(client_id: int) -> bool:
    """Mark today’s booking as no-show."""
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            WITH todayb AS (
              SELECT b.id
                FROM bookings b
                JOIN sessions s ON s.id = b.session_id
               WHERE b.client_id = :cid
                 AND s.session_date = CURRENT_DATE
                 AND (b.status IS NULL OR b.status IN ('booked','confirmed'))
               ORDER BY s.start_time
               LIMIT 1
            )
            UPDATE bookings b
               SET status = 'no_show'
              FROM todayb
             WHERE b.id = todayb.id
            RETURNING b.id
        """), {"cid": client_id}).first()
        return bool(r)

def cancel_sessions_from(start_date: date) -> int:
    """Cancel all sessions from a date forward. Returns count."""
    from .db import get_session
    with get_session() as s:
        res = s.execute(text("""
            UPDATE sessions
               SET status = 'cancelled'
             WHERE session_date >= :d
               AND status <> 'cancelled'
        """), {"d": start_date}).rowcount
        return int(res or 0)
