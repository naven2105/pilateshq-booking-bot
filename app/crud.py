# app/crud.py
"""
Thin SQL helpers for data access.
Keeps raw SQL and table knowledge in one place; business logic stays in admin/booking/tasks.
All functions lazy-import get_session to avoid circular imports.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from sqlalchemy import text

# ---------- Clients ----------

def list_clients(limit: int = 20) -> List[Dict[str, Any]]:
    """Return latest clients (by created_at/id) for pickers."""
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
    """ILIKE search by name, used for admin pickers & NLP resolution."""
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
    """Fullish client profile for VIEW/UPDATE screens."""
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
    """Lookup client by WhatsApp number; returns first match or None."""
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
    """
    Upsert client by wa_number (ON CONFLICT DO UPDATE name).
    Returns the row after insert/update.
    """
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
    """
    Idempotent: returns existing client, or inserts '(new)' name and returns it.
    """
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
    """Set (day, month) for a client’s birthday."""
    from .db import get_session
    with get_session() as s:
        s.execute(text("""
            UPDATE clients
               SET birthday_day = :d, birthday_month = :m
             WHERE id = :cid
        """), {"d": day, "m": month, "cid": client_id})
        return True

def update_client_medical(client_id: int, note: str, append: bool = True) -> bool:
    """
    Update medical_notes:
    - append=True: append with newline (default)
    - append=False: replace with new text
    """
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
    """Add/subtract credits, clamped at >= 0."""
    from .db import get_session
    with get_session() as s:
        s.execute(text("""
            UPDATE clients
               SET credits = GREATEST(0, COALESCE(credits,0) + :d)
             WHERE id = :cid
        """), {"d": delta, "cid": client_id})

# ---------- Sessions/Bookings ----------
# NOTE: Wire these in your schema as needed; referenced by admin/tasks flows.

def find_session_by_date_time(session_date, hhmm: str):
    """
    Optional helper (implement if not present):
    Return session row {id, session_date, start_time, capacity, booked_count, ...}
    matching date + time string 'HH:MM'.
    """
    from .db import get_session
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions
            WHERE session_date = :d AND to_char(start_time, 'HH24:MI') = :t
            LIMIT 1
        """), {"d": session_date, "t": hhmm}).mappings().first()
        return dict(r) if r else None

def cancel_next_booking_for_client(client_id: int) -> bool:
    """
    Optional helper: mark the next upcoming booking cancelled & increment credits.
    Concrete SQL depends on your 'bookings' schema.
    """
    return False  # placeholder

def mark_no_show_today(client_id: int) -> bool:
    """
    Optional helper: mark today's booking as no-show (decrement credit or flag).
    Concrete SQL depends on your 'bookings' schema.
    """
    return False  # placeholder

def list_days_with_open_slots(days: int = 21, limit_days: int = 10):
    """Used by admin to show open days (if you keep the legacy menu)."""
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date, COUNT(*) AS slots
            FROM sessions
            WHERE session_date >= CURRENT_DATE
              AND session_date < CURRENT_DATE + :days * INTERVAL '1 day'
              AND status = 'open'
            GROUP BY session_date
            ORDER BY session_date
            LIMIT :lim
        """), {"days": days, "lim": limit_days}).mappings().all()
        return [dict(r) for r in rows]

def list_slots_for_day(session_date):
    """List slots for a specific day with remaining seats."""
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   (capacity - booked_count) AS seats_left, status
            FROM sessions
            WHERE session_date = :d AND status IN ('open','full')
            ORDER BY start_time
        """), {"d": session_date}).mappings().all()
        return [dict(r) for r in rows]

# For tasks endpoints:
def sessions_next_hour():
    """Return sessions starting within the next hour (implement per schema)."""
    return []

def sessions_tomorrow():
    """Return sessions occurring tomorrow (implement per schema)."""
    return []

def sessions_for_day(d):
    """Return all sessions for date d (implement per schema)."""
    return []

def clients_for_session(session_id: int):
    """Return clients booked into session_id (implement per schema)."""
    return []
