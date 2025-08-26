# app/crud.py
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from .db import get_session

def list_clients(limit: int = 20):
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, wa_number, COALESCE(NULLIF(name,''),'(no name)') AS name, plan
            FROM clients
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT :lim
        """), {"lim": limit}).mappings().all()
        return [dict(r) for r in rows]

def get_or_create_client(wa_number: str, name: str = "") -> Dict[str, Any]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, wa_number, name, plan, household_id, birthday_day, birthday_month, medical_notes, notes
            FROM clients WHERE wa_number = :wa LIMIT 1
        """), {"wa": wa_number}).mappings().first()
        if row: return dict(row)
        s.execute(text("INSERT INTO clients (wa_number, name) VALUES (:wa, :nm)"),
                  {"wa": wa_number, "nm": name or ""})
        row = s.execute(text("""
            SELECT id, wa_number, name, plan, household_id, birthday_day, birthday_month, medical_notes, notes
            FROM clients WHERE wa_number = :wa LIMIT 1
        """), {"wa": wa_number}).mappings().first()
        return dict(row)

def list_available_slots(days: int = 14, min_seats: int = 1, limit: int = 10,
                         start_from: Optional[date] = None) -> List[Dict[str, Any]]:
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

def hold_or_reserve_slot(session_id: int, seats: int = 1) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        row = s.execute(text("""
            UPDATE sessions
            SET booked_count = booked_count + :seats,
                status = CASE WHEN (booked_count + :seats) >= capacity THEN 'full' ELSE status END
            WHERE id = :sid AND (booked_count + :seats) <= capacity
            RETURNING id, session_date, start_time, capacity, booked_count, status
        """), {"sid": session_id, "seats": seats}).mappings().first()
        return dict(row) if row else None

def release_slot(session_id: int, seats: int = 1) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        row = s.execute(text("""
            UPDATE sessions
            SET booked_count = GREATEST(0, booked_count - :seats), status='open'
            WHERE id = :sid
            RETURNING id, session_date, start_time, capacity, booked_count, status
        """), {"sid": session_id, "seats": seats}).mappings().first()
        return dict(row) if row else None
