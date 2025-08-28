# app/crud.py
from __future__ import annotations
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from .db import get_session

# ---------- Clients ----------
def get_or_create_client(wa_number: str, name: str = "") -> Dict[str, Any]:
    """Find client by wa_number; if missing, create it (name optional)."""
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'') AS name,
                   plan, household_id, birthday_day, birthday_month, medical_notes, notes, created_at
            FROM clients WHERE wa_number = :wa LIMIT 1
        """), {"wa": wa_number}).mappings().first()
        if row:
            return dict(row)
        s.execute(text("""
            INSERT INTO clients (wa_number, name)
            VALUES (:wa, :nm)
            ON CONFLICT (wa_number) DO NOTHING
        """), {"wa": wa_number, "nm": (name or "")[:120]})
        row = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'') AS name,
                   plan, household_id, birthday_day, birthday_month, medical_notes, notes, created_at
            FROM clients WHERE wa_number = :wa LIMIT 1
        """), {"wa": wa_number}).mappings().first()
        return dict(row) if row else {"wa_number": wa_number, "name": name or ""}

def list_clients(limit: int = 20) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name, plan,
                   birthday_day, birthday_month, medical_notes, created_at
            FROM clients
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT :lim
        """), {"lim": max(1, min(limit, 100))}).mappings().all()
        return [dict(r) for r in rows]

def find_clients_by_name(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    name = (name or "").strip()
    if not name:
        return []
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name, plan
            FROM clients
            WHERE name ILIKE :q
            ORDER BY name ASC
            LIMIT :lim
        """), {"q": f"%{name}%", "lim": max(1, min(limit, 10))}).mappings().all()
        return [dict(r) for r in rows]

def get_client_profile(client_id: int) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan, birthday_day, birthday_month, medical_notes, notes,
                   household_id, created_at
            FROM clients WHERE id = :cid
        """), {"cid": client_id}).mappings().first()
        return dict(row) if row else None

def create_client(name: str, wa_number: str) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        s.execute(text("""
            INSERT INTO clients (name, wa_number)
            VALUES (:nm, :wa)
            ON CONFLICT (wa_number) DO UPDATE SET name = EXCLUDED.name
        """), {"nm": name.strip()[:120], "wa": wa_number.strip()})
        row = s.execute(text("""
            SELECT id, name, wa_number, plan FROM clients WHERE wa_number = :wa
        """), {"wa": wa_number.strip()}).mappings().first()
        return dict(row) if row else None

def update_client_dob(client_id: int, day: int, month: int) -> bool:
    with get_session() as s:
        res = s.execute(text("""
            UPDATE clients
            SET birthday_day = :d, birthday_month = :m
            WHERE id = :cid
        """), {"d": day, "m": month, "cid": client_id})
        return res.rowcount > 0

def update_client_medical(client_id: int, note: str, append: bool = True) -> bool:
    with get_session() as s:
        if append:
            res = s.execute(text("""
                UPDATE clients
                SET medical_notes = CONCAT(COALESCE(NULLIF(medical_notes,''),''),
                                           CASE WHEN COALESCE(NULLIF(medical_notes,''),'') = '' THEN '' ELSE E'\n' END,
                                           :n)
                WHERE id = :cid
            """), {"n": note.strip(), "cid": client_id})
        else:
            res = s.execute(text("""
                UPDATE clients SET medical_notes = :n WHERE id = :cid
            """), {"n": note.strip(), "cid": client_id})
        return res.rowcount > 0

# ---------- Sessions / Availability ----------
def list_available_slots(days: int = 14, min_seats: int = 1, limit: int = 10,
                         start_from: Optional[date] = None) -> List[Dict[str, Any]]:
    days = max(1, min(days, 60))
    limit = max(1, min(limit, 50))
    start_from = start_from or date.today()
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   (capacity - booked_count) AS seats_left, status
            FROM sessions
            WHERE session_date >= :start_date
              AND session_date <  :end_date
              AND status = 'open'
              AND (capacity - booked_count) >= :min_seats
            ORDER BY session_date, start_time
            LIMIT :limit
        """), {
            "start_date": start_from,
            "end_date": start_from + timedelta(days=days),
            "min_seats": min_seats,
            "limit": limit,
        }).mappings().all()
        return [dict(r) for r in rows]

def list_days_with_open_slots(days: int = 21, limit_days: int = 10) -> List[Dict[str, Any]]:
    start_from = date.today()
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date, COUNT(*) AS slots
            FROM sessions
            WHERE session_date >= :start_date
              AND session_date <  :end_date
              AND status = 'open'
              AND (capacity - booked_count) > 0
            GROUP BY session_date
            ORDER BY session_date
            LIMIT :lim
        """), {
            "start_date": start_from,
            "end_date": start_from + timedelta(days=days),
            "lim": max(1, min(limit_days, 30))
        }).mappings().all()
        return [dict(r) for r in rows]

def list_slots_for_day(session_date: date, limit: int = 20) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   (capacity - booked_count) AS seats_left, status
            FROM sessions
            WHERE session_date = :d AND (capacity - booked_count) > 0 AND status = 'open'
            ORDER BY start_time
            LIMIT :lim
        """), {"d": session_date, "lim": max(1, min(limit, 50))}).mappings().all()
        return [dict(r) for r in rows]

def find_session_by_date_time(session_date: date, hhmm: str) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions
            WHERE session_date = :d AND start_time = :t
            LIMIT 1
        """), {"d": session_date, "t": hhmm}).mappings().first()
        return dict(row) if row else None

# ---------- Bookings ----------
def create_booking(session_id: int, client_id: int, seats: int = 1, status: str = "confirmed") -> bool:
    with get_session() as s:
        slot = s.execute(text("""
            SELECT id, capacity, booked_count FROM sessions WHERE id = :sid FOR UPDATE
        """), {"sid": session_id}).mappings().first()
        if not slot or (slot["booked_count"] + seats > slot["capacity"]):
            return False
        s.execute(text("""
            INSERT INTO bookings (client_id, session_id, seats, status)
            VALUES (:cid, :sid, :seats, :status)
            ON CONFLICT (client_id, session_id)
            DO UPDATE SET status = EXCLUDED.status, seats = EXCLUDED.seats
        """), {"cid": client_id, "sid": session_id, "seats": seats, "status": status})
        s.execute(text("""
            UPDATE sessions
            SET booked_count = booked_count + :seats,
                status = CASE WHEN (booked_count + :seats) >= capacity THEN 'full' ELSE status END
            WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        return True

def cancel_booking(client_id: int, session_id: int) -> bool:
    with get_session() as s:
        row = s.execute(text("""
            UPDATE bookings
            SET status = 'cancelled'
            WHERE client_id = :cid AND session_id = :sid
              AND status IN ('held','confirmed')
            RETURNING seats
        """), {"cid": client_id, "sid": session_id}).first()
        if not row:
            return False
        seats = int(row[0] or 1)
        s.execute(text("""
            UPDATE sessions
            SET booked_count = GREATEST(0, booked_count - :seats),
                status = CASE WHEN booked_count - :seats < capacity THEN 'open' ELSE status END
            WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        return True

def cancel_next_booking_for_client(client_id: int) -> bool:
    with get_session() as s:
        row = s.execute(text("""
            SELECT b.session_id, b.seats
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            WHERE b.client_id = :cid AND b.status IN ('held','confirmed')
              AND s.session_date >= CURRENT_DATE
            ORDER BY s.session_date, s.start_time
            LIMIT 1
        """), {"cid": client_id}).mappings().first()
        if not row:
            return False
        return cancel_booking(client_id, row["session_id"])

def mark_no_show_today(client_id: int) -> bool:
    with get_session() as s:
        res = s.execute(text("""
            UPDATE bookings b
            SET status = 'noshow'
            FROM sessions s
            WHERE b.session_id = s.id
              AND b.client_id = :cid
              AND s.session_date = CURRENT_DATE
              AND b.status IN ('held','confirmed')
        """), {"cid": client_id})
        return res.rowcount > 0
