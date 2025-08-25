# app/booking.py
"""
Booking helpers (admin-driven). Clients don’t self-book.
Use these to reserve/release/check slots from Nadine’s WhatsApp admin menu.
"""
from sqlalchemy import text
from .db import get_session

def admin_reserve(client_wa: str, session_id: int, seats: int = 1) -> bool:
    with get_session() as s:
        # ensure slot has space
        row = s.execute(text("""
            SELECT capacity, booked_count FROM sessions WHERE id = :sid FOR UPDATE
        """), {"sid": session_id}).mappings().first()
        if not row or row["booked_count"] + seats > row["capacity"]:
            return False
        s.execute(text("""
            UPDATE sessions
            SET booked_count = booked_count + :seats,
                status = CASE WHEN booked_count >= capacity THEN 'full' ELSE 'open' END
            WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        # (Optional) write to a joins table later for reporting
        return True

def admin_release(session_id: int, seats: int = 1) -> bool:
    with get_session() as s:
        s.execute(text("""
            UPDATE sessions
            SET booked_count = GREATEST(0, booked_count - :seats),
                status = 'open'
            WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        return True

def list_next_open_slots(limit: int = 10):
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count,
                   (capacity - booked_count) AS seats_left, status
            FROM sessions
            WHERE session_date >= CURRENT_DATE AND status = 'open'
            ORDER BY session_date, start_time
            LIMIT :lim
        """), {"lim": limit}).mappings().all()
        return [dict(r) for r in rows]
