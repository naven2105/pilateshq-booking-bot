# app/crud.py
from __future__ import annotations
from datetime import date, datetime, timedelta, time
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from zoneinfo import ZoneInfo

ZA = ZoneInfo("Africa/Johannesburg")

# NOTE: to reduce circular-import risks, import get_session lazily inside functions.


# ──────────────────────────────────────────────────────────────────────────────
# Clients
# ──────────────────────────────────────────────────────────────────────────────

def list_clients(limit: int = 20) -> List[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, wa_number,
                   COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan, credits
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
            SELECT id, wa_number,
                   COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan, credits
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
    """Return client row if exists, else create one with just wa_number."""
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


# ──────────────────────────────────────────────────────────────────────────────
# Sessions / Bookings (helpers used by tasks & admin flows)
# ──────────────────────────────────────────────────────────────────────────────

def sessions_for_day_all(d: date) -> List[Dict[str, Any]]:
    """All sessions for the day (including past times)."""
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = :d
            ORDER BY start_time
        """), {"d": d}).mappings().all()
        return [dict(r) for r in rows]

def sessions_for_day_upcoming(d: date) -> List[Dict[str, Any]]:
    """Only sessions that have not started yet today (ZA time). For other dates, returns all."""
    from .db import get_session
    now_za = datetime.now(ZA)
    if d == now_za.date():
        with get_session() as s:
            rows = s.execute(text("""
                SELECT id, session_date, start_time, capacity, booked_count, status, notes
                FROM sessions
                WHERE session_date = :d
                  AND start_time >= :nowt
                ORDER BY start_time
            """), {"d": d, "nowt": now_za.time()}).mappings().all()
            return [dict(r) for r in rows]
    # not today → return all
    return sessions_for_day_all(d)

def sessions_for_day(d: date) -> List[Dict[str, Any]]:
    """
    Backward-compat wrapper: default to upcoming-only for 'today', else all.
    Used by older code paths.
    """
    return sessions_for_day_upcoming(d)

def sessions_next_hour() -> List[Dict[str, Any]]:
    """Sessions starting in the next ~hour (ZA time) today."""
    from .db import get_session
    now = datetime.now(ZA)
    today = now.date()
    start = (now.replace(minute=0, second=0, microsecond=0) +
             timedelta(hours=0)).time()
    end = (now + timedelta(hours=1)).time()
    # guard around midnight wrap
    if end < start:
        end = time(23, 59, 59)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = :d
              AND start_time >= :start
              AND start_time <  :end
            ORDER BY start_time
        """), {"d": today, "start": start, "end": end}).mappings().all()
        return [dict(r) for r in rows]

def sessions_tomorrow() -> List[Dict[str, Any]]:
    """All of tomorrow's sessions."""
    from .db import get_session
    tomorrow = date.today() + timedelta(days=1)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = :d
            ORDER BY start_time
        """), {"d": tomorrow}).mappings().all()
        return [dict(r) for r in rows]

def clients_for_session(session_id: int) -> List[Dict[str, Any]]:
    """
    Return clients booked into a session. Expects bookings table with client_id/session_id.
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.id, c.wa_number,
                   COALESCE(NULLIF(c.name,''),'(no name)') AS name,
                   c.plan, c.credits
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            WHERE b.session_id = :sid
              AND b.status IN ('confirmed','reserved')
            ORDER BY c.name NULLS LAST
        """), {"sid": session_id}).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Optional admin helpers (only if your admin flows use them)
# ──────────────────────────────────────────────────────────────────────────────

def list_days_with_open_slots(days: int = 21, limit_days: int = 10) -> List[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date, COUNT(*) AS slots
            FROM sessions
            WHERE session_date >= CURRENT_DATE
              AND session_date < CURRENT_DATE + :days::interval
              AND status = 'open'
            GROUP BY session_date
            ORDER BY session_date
            LIMIT :lim
        """), {"days": f"{days} days", "lim": limit_days}).mappings().all()
        return [dict(r) for r in rows]

def list_slots_for_day(d: date) -> List[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   (capacity - booked_count) AS seats_left, status
            FROM sessions
            WHERE session_date = :d AND status = 'open'
            ORDER BY start_time
        """), {"d": d}).mappings().all()
        return [dict(r) for r in rows]

def find_session_by_date_time(d: date, hhmm: str) -> Optional[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions
            WHERE session_date = :d AND start_time = :t
            LIMIT 1
        """), {"d": d, "t": hhmm}).mappings().first()
        return dict(r) if r else None

def create_booking(session_id: int, client_id: int, seats: int = 1, status: str = "confirmed") -> bool:
    from .db import get_session
    with get_session() as s:
        s.execute(text("""
            INSERT INTO bookings (session_id, client_id, seats, status)
            VALUES (:sid, :cid, :seats, :st)
            ON CONFLICT (client_id, session_id) DO NOTHING
        """), {"sid": session_id, "cid": client_id, "seats": seats, "st": status})
        # Let DB triggers handle booked_count and overbooking prevention if present.
        return True

def cancel_next_booking_for_client(client_id: int) -> bool:
    from .db import get_session
    with get_session() as s:
        # find the next upcoming booking for this client (today or future)
        r = s.execute(text("""
            WITH next_b AS (
              SELECT b.id
              FROM bookings b
              JOIN sessions s ON s.id = b.session_id
              WHERE b.client_id = :cid
                AND b.status IN ('confirmed','reserved')
                AND (s.session_date > CURRENT_DATE
                     OR (s.session_date = CURRENT_DATE AND s.start_time >= CURRENT_TIME))
              ORDER BY s.session_date, s.start_time
              LIMIT 1
            )
            UPDATE bookings b
               SET status = 'cancelled'
            FROM next_b
            WHERE b.id = next_b.id
            RETURNING b.id
        """), {"cid": client_id}).mappings().first()
        return bool(r)

def mark_no_show_today(client_id: int) -> bool:
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            WITH todays AS (
              SELECT b.id
              FROM bookings b
              JOIN sessions s ON s.id = b.session_id
              WHERE b.client_id = :cid
                AND s.session_date = CURRENT_DATE
                AND b.status IN ('confirmed','reserved')
              ORDER BY s.start_time
              LIMIT 1
            )
            UPDATE bookings b
               SET status = 'no_show'
            FROM todays
            WHERE b.id = todays.id
            RETURNING b.id
        """), {"cid": client_id}).mappings().first()
        return bool(r)
