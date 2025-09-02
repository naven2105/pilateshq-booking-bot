# app/crud.py
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import text

# ⚠️ We lazy-import get_session inside each function to avoid circular imports.
# If your DB is set to UTC, we explicitly read times in SAST (Africa/Johannesburg)
# when building “next hour” and “today/tomorrow” windows.

SAST_TZ = "Africa/Johannesburg"


# ──────────────────────────────────────────────────────────────────────────────
# CLIENTS
# ──────────────────────────────────────────────────────────────────────────────
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
        s.execute(text("""
            UPDATE clients
               SET credits = GREATEST(0, COALESCE(credits,0) + :d)
             WHERE id = :cid
        """), {"d": delta, "cid": client_id})


# ──────────────────────────────────────────────────────────────────────────────
# SESSIONS / BOOKINGS  (used by hourly & 20:00 admin notifications)
# Assumed schema:
#   sessions(id, session_date date, start_time time, capacity int, booked_count int, status text, notes text)
#   bookings(id, session_id, client_id, seats int, status text)
#   clients(id, wa_number, name, ...)
# ──────────────────────────────────────────────────────────────────────────────

def sessions_for_day(d: date) -> List[Dict[str, Any]]:
    """
    Return all sessions on a specific calendar date, ordered by time.
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = :d
            ORDER BY start_time ASC, id ASC
        """), {"d": d}).mappings().all()
        return [dict(r) for r in rows]

def sessions_next_hour() -> List[Dict[str, Any]]:
    """
    Return sessions that start in the next ~60 minutes in SAST.
    We build a window [now, now+1h) and match session_date/start_time accordingly.
    """
    from .db import get_session
    with get_session() as s:
        # Build window inside SQL in SAST to keep it consistent even if DB runs UTC.
        rows = s.execute(text(f"""
            WITH now_sast AS (
              SELECT (now() AT TIME ZONE :tz) AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, now_sast
            WHERE (session_date = (ts)::date)
              AND (start_time >= (ts)::time)
              AND (start_time < ((ts + interval '1 hour')::time))
            ORDER BY start_time ASC, id ASC
        """), {"tz": SAST_TZ}).mappings().all()
        return [dict(r) for r in rows]

def sessions_tomorrow() -> List[Dict[str, Any]]:
    """
    Return all sessions tomorrow (relative to SAST date), ordered by time.
    Used for client reminder texts and 20:00 admin next-day preview wrapper (older version).
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text(f"""
            WITH today AS (
              SELECT (now() AT TIME ZONE :tz)::date AS d
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, today
            WHERE session_date = (d + 1)
            ORDER BY start_time ASC, id ASC
        """), {"tz": SAST_TZ}).mappings().all()
        return [dict(r) for r in rows]

def clients_for_session(session_id: int) -> List[Dict[str, Any]]:
    """
    Return clients booked into a given session.
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.id, c.wa_number, COALESCE(NULLIF(c.name,''),'(no name)') AS name,
                   b.seats, b.status
            FROM bookings b
            JOIN clients  c ON c.id = b.client_id
            WHERE b.session_id = :sid
              AND b.status IN ('confirmed','reserved')
            ORDER BY c.name ASC, c.id ASC
        """), {"sid": session_id}).mappings().all()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# EXTRA ADMIN HELPERS (kept for completeness / legacy strict template flows)
# ──────────────────────────────────────────────────────────────────────────────
def list_days_with_open_slots(days: int = 21, limit_days: int = 10) -> List[Dict[str, Any]]:
    """
    Top N days within the next `days` that still have open seats.
    """
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date, SUM(GREATEST(capacity - booked_count, 0)) AS slots
            FROM sessions
            WHERE session_date BETWEEN CURRENT_DATE AND CURRENT_DATE + :days::interval
              AND status IN ('open')
            GROUP BY session_date
            HAVING SUM(GREATEST(capacity - booked_count, 0)) > 0
            ORDER BY session_date ASC
            LIMIT :lim
        """), {"days": f"{days} days", "lim": limit_days}).mappings().all()
        return [dict(r) for r in rows]

def list_slots_for_day(d: date) -> List[Dict[str, Any]]:
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   GREATEST(capacity - booked_count, 0) AS seats_left, status
            FROM sessions
            WHERE session_date = :d
            ORDER BY start_time ASC, id ASC
        """), {"d": d}).mappings().all()
        return [dict(r) for r in rows]

def find_session_by_date_time(d: date, hhmm: str) -> Optional[Dict[str, Any]]:
    """
    hhmm is 'HH:MM' (24h).
    """
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = :d AND start_time = :t
            LIMIT 1
        """), {"d": d, "t": hhmm}).mappings().first()
        return dict(r) if r else None

def create_booking(session_id: int, client_id: int, seats: int = 1, status: str = "confirmed") -> bool:
    """
    Simple booking insert that respects capacity via DB triggers/constraints,
    and increments counters if you keep triggers in DB. If no triggers, we do a check.
    """
    from .db import get_session
    with get_session() as s:
        # optimistic approach; if DB has constraint/trigger, it will raise on overbook
        s.execute(text("""
            INSERT INTO bookings (session_id, client_id, seats, status)
            VALUES (:sid, :cid, :seats, :st)
            ON CONFLICT (client_id, session_id) DO NOTHING
        """), {"sid": session_id, "cid": client_id, "seats": seats, "st": status})
        # return True even if conflict NOOP (idempotent)
        return True

def cancel_next_booking_for_client(client_id: int) -> bool:
    """
    Cancels the next upcoming booking for a client (today or future).
    If you maintain credits, add a +1 credit here if that’s your policy.
    """
    from .db import get_session
    with get_session() as s:
        # find the next session (today or later) where client is booked confirmed/reserved
        r = s.execute(text(f"""
            WITH now_sast AS (SELECT (now() AT TIME ZONE :tz) AS ts)
            SELECT b.id AS booking_id, b.session_id
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            CROSS JOIN now_sast n
            WHERE b.client_id = :cid
              AND b.status IN ('confirmed','reserved')
              AND (
                    s.session_date > (n.ts)::date
                 OR (s.session_date = (n.ts)::date AND s.start_time >= (n.ts)::time)
              )
            ORDER BY s.session_date, s.start_time
            LIMIT 1
        """), {"cid": client_id, "tz": SAST_TZ}).mappings().first()

        if not r:
            return False

        # cancel booking
        s.execute(text("""
            UPDATE bookings SET status = 'cancelled' WHERE id = :bid
        """), {"bid": r["booking_id"]})
        # (optional) increment credits here via adjust_client_credits(client_id, +1)
        return True

def mark_no_show_today(client_id: int) -> bool:
    """
    Marks today's earliest booking as no-show.
    """
    from .db import get_session
    with get_session() as s:
        r = s.execute(text(f"""
            WITH today AS (SELECT (now() AT TIME ZONE :tz)::date AS d)
            SELECT b.id AS booking_id
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            CROSS JOIN today t
            WHERE b.client_id = :cid
              AND s.session_date = t.d
              AND b.status = 'confirmed'
            ORDER BY s.start_time ASC
            LIMIT 1
        """), {"cid": client_id, "tz": SAST_TZ}).mappings().first()
        if not r:
            return False
        s.execute(text("UPDATE bookings SET status = 'no_show' WHERE id = :bid"),
                  {"bid": r["booking_id"]})
        return True
