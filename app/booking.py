# app/booking.py
"""
Booking helpers (admin-driven).
These enforce capacity changes on sessions with simple, safe counters.
"""

from sqlalchemy import text
from .db import get_session

def admin_reserve(client_wa: str, session_id: int, seats: int = 1) -> bool:
    """
    Reserve seats on a session.
    Concurrency: SELECT ... FOR UPDATE locks the row during capacity check.
    Returns True if reserved, False if capacity insufficient.
    """
    with get_session() as s:
        row = s.execute(text("""
            SELECT capacity, booked_count
            FROM sessions
            WHERE id = :sid
            FOR UPDATE
        """), {"sid": session_id}).mappings().first()
        if not row or row["booked_count"] + seats > row["capacity"]:
            return False
        s.execute(text("""
            UPDATE sessions
               SET booked_count = booked_count + :seats,
                   status = CASE
                              WHEN booked_count + :seats >= capacity THEN 'full'
                              ELSE 'open'
                            END
             WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        # Optionally insert into a join table client<->session here.
        return True

def admin_release(session_id: int, seats: int = 1) -> bool:
    """Release seats and mark slot open again."""
    with get_session() as s:
        s.execute(text("""
            UPDATE sessions
               SET booked_count = GREATEST(0, booked_count - :seats),
                   status = 'open'
             WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        return True

def list_next_open_slots(limit: int = 10):
    """Show the next n open sessions to help the admin pick a slot."""
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
