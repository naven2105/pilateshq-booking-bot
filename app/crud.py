from __future__ import annotations
from datetime import date, datetime, timedelta, time as dtime
from typing import Any, Dict, List, Optional
from sqlalchemy import text

# NOTE: we lazy-import get_session in each function to avoid circular imports.

# ---------- Clients (existing minimal set you already had) ----------
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

# ---------- Sessions & bookings for reminders (READ-ONLY) ----------
def sessions_for_day(d: date) -> List[Dict[str, Any]]:
    """Return all sessions for a given date (ordered), with basic counts."""
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id,
                   session_date,
                   start_time,
                   capacity,
                   booked_count,
                   status,
                   COALESCE(notes,'') AS notes
              FROM sessions
             WHERE session_date = :d
             ORDER BY start_time ASC
        """), {"d": d}).mappings().all()
        return [dict(r) for r in rows]

def sessions_next_hour(now_ts: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Return sessions that start within the next 60 minutes (today only)."""
    from .db import get_session
    now_ts = now_ts or datetime.utcnow()
    today = now_ts.date()
    start = now_ts.time().strftime("%H:%M:%S")
    end_dt = (now_ts + timedelta(hours=1))
    end = end_dt.time().strftime("%H:%M:%S")
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
              FROM sessions
             WHERE session_date = :today
               AND start_time >= :start
               AND start_time <  :end
             ORDER BY start_time
        """), {"today": today, "start": start, "end": end}).mappings().all()
        return [dict(r) for r in rows]

def clients_for_session(session_id: int) -> List[Dict[str, Any]]:
    """Return clients booked on a session. STRICTLY READ-ONLY."""
    from .db import get_session
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.id, c.wa_number, COALESCE(NULLIF(c.name,''),'(no name)') AS name
              FROM bookings b
              JOIN clients  c ON c.id = b.client_id
             WHERE b.session_id = :sid
               AND b.status IN ('confirmed','reserved')
             ORDER BY c.name
        """), {"sid": session_id}).mappings().all()
        return [dict(r) for r in rows]
