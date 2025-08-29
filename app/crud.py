# app/crud.py
from __future__ import annotations
from datetime import date, datetime, timedelta, time as dtime
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from .db import get_session

# ---------- Clients ----------
def list_clients(limit: int = 20) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name, plan, credits
            FROM clients
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT :lim
        """), {"lim": limit}).mappings().all()
        return [dict(r) for r in rows]

def find_clients_by_name(name: str, limit: int = 6) -> List[Dict[str, Any]]:
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
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan, birthday_day, birthday_month, medical_notes, notes,
                   household_id, created_at, credits
            FROM clients WHERE id = :cid
        """), {"cid": client_id}).mappings().first()
        return dict(r) if r else None

def get_client_by_wa(wa_number: str) -> Optional[Dict[str, Any]]:
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
    # assumes phone is already normalized by caller if needed
    with get_session() as s:
        # upsert by phone
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

def update_client_dob(client_id: int, day: int, month: int) -> bool:
    with get_session() as s:
        s.execute(text("""
            UPDATE clients
               SET birthday_day = :d, birthday_month = :m
             WHERE id = :cid
        """), {"d": day, "m": month, "cid": client_id})
        return True

def update_client_medical(client_id: int, note: str, append: bool = True) -> bool:
    with get_session() as s:
        if append:
            s.execute(text("""
                UPDATE clients
                   SET medical_notes = trim(BOTH FROM
                       COALESCE(NULLIF(medical_notes,''),'') || CASE WHEN medical_notes IS NULL OR medical_notes = '' THEN '' ELSE E'\n' END || :note)
                 WHERE id = :cid
            """), {"note": note[:500], "cid": client_id})
        else:
            s.execute(text("""
                UPDATE clients SET medical_notes = :note WHERE id = :cid
            """), {"note": note[:500], "cid": client_id})
        return True

def adjust_client_credits(client_id: int, delta: int) -> None:
    with get_session() as s:
        s.execute(text("UPDATE clients SET credits = GREATEST(0, COALESCE(credits,0) + :d) WHERE id = :cid"),
                  {"d": delta, "cid": client_id})

# ---------- Sessions / Availability ----------
def list_days_with_open_slots(days: int = 21, limit_days: int = 10) -> List[Dict[str, Any]]:
    start = date.today()
    end = start + timedelta(days=max(1, days))
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date, COUNT(*) AS slots
              FROM sessions
             WHERE session_date >= :start
               AND session_date <  :end
               AND status = 'open'
               AND (capacity - booked_count) > 0
             GROUP BY session_date
             ORDER BY session_date
             LIMIT :lim
        """), {"start": start, "end": end, "lim": limit_days}).mappings().all()
        return [dict(r) for r in rows]

def list_slots_for_day(day: date) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   (capacity - booked_count) AS seats_left, status
              FROM sessions
             WHERE session_date = :d
               AND (capacity - booked_count) > 0
             ORDER BY start_time
        """), {"d": day}).mappings().all()
        return [dict(r) for r in rows]

def find_session_by_date_time(day: date, hhmm: str) -> Optional[Dict[str, Any]]:
    # hhmm like "08:00" or "8:00"
    if len(hhmm) <= 5:
        hhmm = hhmm.zfill(5)  # "8:00" -> "08:00"
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   (capacity - booked_count) AS seats_left, status
              FROM sessions
             WHERE session_date = :d AND start_time = :t::time
             LIMIT 1
        """), {"d": day, "t": hhmm}).mappings().first()
        return dict(r) if r else None

# ---------- Bookings ----------
def create_booking(session_id: int, client_id: int, seats: int = 1, status: str = "confirmed") -> bool:
    with get_session() as s:
        # check capacity
        slot = s.execute(text("SELECT capacity, booked_count FROM sessions WHERE id = :sid FOR UPDATE"),
                         {"sid": session_id}).mappings().first()
        if not slot:
            return False
        if slot["booked_count"] + seats > slot["capacity"]:
            return False

        # insert booking (unique client_id+session_id)
        s.execute(text("""
            INSERT INTO bookings (client_id, session_id, seats, status)
            VALUES (:cid, :sid, :seats, :status)
            ON CONFLICT (client_id, session_id) DO UPDATE SET status = EXCLUDED.status
        """), {"cid": client_id, "sid": session_id, "seats": seats, "status": status})

        # bump session counters
        s.execute(text("""
            UPDATE sessions
               SET booked_count = booked_count + :seats,
                   status = CASE WHEN (booked_count + :seats) >= capacity THEN 'full' ELSE status END
             WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        return True

def cancel_next_booking_for_client(client_id: int) -> bool:
    today = date.today()
    with get_session() as s:
        bk = s.execute(text("""
            SELECT b.id, b.session_id, s.session_date
              FROM bookings b
              JOIN sessions s ON s.id = b.session_id
             WHERE b.client_id = :cid
               AND s.session_date >= :today
               AND b.status IN ('confirmed','held')
             ORDER BY s.session_date, s.start_time
             LIMIT 1
        """), {"cid": client_id, "today": today}).mappings().first()
        if not bk:
            return False
        # mark cancelled + reduce count
        s.execute(text("UPDATE bookings SET status = 'cancelled' WHERE id = :bid"), {"bid": bk["id"]})
        s.execute(text("""
            UPDATE sessions
               SET booked_count = GREATEST(0, booked_count - 1),
                   status = 'open'
             WHERE id = :sid
        """), {"sid": bk["session_id"]})
        # credit back 1
        adjust_client_credits(client_id, +1)
        return True

def mark_no_show_today(client_id: int) -> bool:
    today = date.today()
    with get_session() as s:
        bk = s.execute(text("""
            SELECT b.id, b.session_id
              FROM bookings b
              JOIN sessions s ON s.id = b.session_id
             WHERE b.client_id = :cid
               AND s.session_date = :today
               AND b.status = 'confirmed'
             ORDER BY s.start_time
             LIMIT 1
        """), {"cid": client_id, "today": today}).mappings().first()
        if not bk:
            return False
        s.execute(text("UPDATE bookings SET status = 'noshow' WHERE id = :bid"), {"bid": bk["id"]})
        # no credit change by default; adjust policy if needed
        return True

def clients_for_session(session_id: int) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.id, c.name, c.wa_number
              FROM bookings b
              JOIN clients c ON c.id = b.client_id
             WHERE b.session_id = :sid
               AND b.status = 'confirmed'
             ORDER BY c.name
        """), {"sid": session_id}).mappings().all()
        return [dict(r) for r in rows]

# ---------- Reminders / schedules ----------
def sessions_next_hour(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.utcnow()
    start = now
    end = now + timedelta(hours=1, minutes=1)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time
              FROM sessions
             WHERE (session_date = :d)
               AND (start_time >= :t_from::time AND start_time < :t_to::time)
        """), {"d": start.date(), "t_from": start.time(), "t_to": end.time()}).mappings().all()
        return [dict(r) for r in rows]

def sessions_tomorrow() -> List[Dict[str, Any]]:
    t = date.today() + timedelta(days=1)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time
              FROM sessions
             WHERE session_date = :d
             ORDER BY start_time
        """), {"d": t}).mappings().all()
        return [dict(r) for r in rows]

def sessions_for_day(d: date) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time
              FROM sessions
             WHERE session_date = :d
             ORDER BY start_time
        """), {"d": d}).mappings().all()
        return [dict(r) for r in rows]
