# app/crud.py
from __future__ import annotations
from datetime import date
from typing import Any, Dict, List, Optional
from sqlalchemy import text

# NOTE: to avoid circular imports, we import get_session INSIDE each function.

# ---------- Clients ----------
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

# ---------- Sessions & Bookings helpers (used by admin/tasks) ----------

def create_booking(session_id: int, client_id: int, seats: int = 1, status: str = "confirmed") -> bool:
    """
    Insert a booking; DB triggers enforce capacity & recalc sessions.
    """
    from .db import get_session
    with get_session() as s:
        s.execute(text("""
            INSERT INTO bookings (session_id, client_id, seats, status)
            VALUES (:sid, :cid, GREATEST(1, :seats), :st)
        """), {"sid": session_id, "cid": client_id, "seats": seats, "st": status})
    return True

def find_session_by_date_time(session_date: date, hhmm: str) -> Optional[Dict[str, Any]]:
    """
    Return a session row by exact date + start_time (HH:MM).
    """
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = :d AND to_char(start_time, 'HH24:MI') = :t
            LIMIT 1
        """), {"d": session_date, "t": hhmm}).mappings().first()
        return dict(r) if r else None

def list_days_with_open_slots(days: int = 21, limit_days: int = 10) -> List[Dict[str, Any]]:
    """
    Aggregate next N days that still have open seats.
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date,
                   COUNT(*) FILTER (WHERE (capacity - booked_count) > 0 AND status = 'open') AS slots
            FROM sessions
            WHERE session_date BETWEEN CURRENT_DATE AND CURRENT_DATE + :span::interval
            GROUP BY session_date
            HAVING COUNT(*) FILTER (WHERE (capacity - booked_count) > 0 AND status = 'open') > 0
            ORDER BY session_date
            LIMIT :lim
        """), {"span": f"{int(days)} days", "lim": limit_days}).mappings().all()
        return [dict(r) for r in rows]

def list_slots_for_day(session_date: date) -> List[Dict[str, Any]]:
    """
    List all slots for a day (ordered), including seats_left.
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   (capacity - booked_count) AS seats_left, status
            FROM sessions
            WHERE session_date = :d
            ORDER BY start_time ASC
        """), {"d": session_date}).mappings().all()
        return [dict(r) for r in rows]

def cancel_next_booking_for_client(client_id: int) -> bool:
    """
    Cancel the client's next upcoming confirmed booking.
    Triggers will recalc session counts.
    """
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT b.id
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            WHERE b.client_id = :cid AND b.status = 'confirmed'
              AND s.session_date >= CURRENT_DATE
            ORDER BY s.session_date ASC, s.start_time ASC
            LIMIT 1
        """), {"cid": client_id}).mappings().first()
        if not r:
            return False
        s.execute(text("UPDATE bookings SET status = 'cancelled' WHERE id = :bid"), {"bid": r["id"]})
        return True

def mark_no_show_today(client_id: int) -> bool:
    """
    Mark today’s booking as 'cancelled' and (optionally) decrement credits.
    Adjust the credits logic to your policy if needed.
    """
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT b.id
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            WHERE b.client_id = :cid AND b.status = 'confirmed'
              AND s.session_date = CURRENT_DATE
            ORDER BY s.start_time ASC
            LIMIT 1
        """), {"cid": client_id}).mappings().first()
        if not r:
            return False
        s.execute(text("UPDATE bookings SET status = 'cancelled' WHERE id = :bid"), {"bid": r["id"]})
        # Optional credit penalty:
        s.execute(text("UPDATE clients SET credits = GREATEST(0, COALESCE(credits,0) - 1) WHERE id = :cid"),
                  {"cid": client_id})
        return True

def clients_for_session(session_id: int) -> List[Dict[str, Any]]:
    """
    All clients with confirmed bookings in a session (for reminders).
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.id, c.wa_number, c.name, c.plan, c.credits
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            WHERE b.session_id = :sid AND b.status = 'confirmed'
            ORDER BY c.name
        """), {"sid": session_id}).mappings().all()
        return [dict(r) for r in rows]

def sessions_for_day(d: date) -> List[Dict[str, Any]]:
    """
    All sessions for a day (for admin summaries).
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions
            WHERE session_date = :d
            ORDER BY start_time
        """), {"d": d}).mappings().all()
        return [dict(r) for r in rows]

def sessions_next_hour() -> List[Dict[str, Any]]:
    """
    Sessions that start within the next 60 minutes (Johannesburg time).
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_za AS (
              SELECT (now() AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions, now_za
            WHERE session_date = (ts::date)
              AND make_time(date_part('hour', start_time)::int, date_part('minute', start_time)::int, 0)
                  BETWEEN date_trunc('minute', ts)::time
                      AND (date_trunc('minute', ts) + interval '60 minutes')::time
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def sessions_tomorrow() -> List[Dict[str, Any]]:
    """
    All sessions scheduled for tomorrow.
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions
            WHERE session_date = CURRENT_DATE + INTERVAL '1 day'
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]
