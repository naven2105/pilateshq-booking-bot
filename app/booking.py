# app/booking.py
"""
Booking helpers (admin-driven).
These enforce capacity changes on sessions with safe counters.
"""

from sqlalchemy import text
from datetime import date, timedelta, datetime
from .db import get_session

# How far ahead to generate recurring bookings (in weeks)
RECURRING_WEEKS_AHEAD = 12


def admin_reserve(client_id: int, session_id: int, seats: int = 1) -> bool:
    """
    Reserve seats on a session and insert into bookings.
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

        # update session capacity counters
        s.execute(text("""
            UPDATE sessions
               SET booked_count = booked_count + :seats,
                   status = CASE
                              WHEN booked_count + :seats >= capacity THEN 'full'
                              ELSE 'open'
                            END
             WHERE id = :sid
        """), {"sid": session_id, "seats": seats})

        # insert booking row
        s.execute(text("""
            INSERT INTO bookings (client_id, session_id, status)
            VALUES (:cid, :sid, 'active')
        """), {"cid": client_id, "sid": session_id})

        s.commit()
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
        s.commit()
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


def _find_session_on(date_str: str, time_str: str):
    """Find a session by date and start_time (HH:MM)."""
    with get_session() as s:
        row = s.execute(text("""
            SELECT id FROM sessions
            WHERE session_date = :d AND start_time = :t
        """), {"d": date_str, "t": time_str}).first()
        return row[0] if row else None


def create_recurring_bookings(client_id: int, weekday: int, time_str: str, slot_type: str):
    """
    Create bookings every week for a given weekday+time.
    Weekday: 0=Mon … 6=Sun
    """
    today = date.today()
    # find next occurrence of this weekday
    days_ahead = (weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # always future, not today
    start_date = today + timedelta(days=days_ahead)

    created = 0
    for wk in range(RECURRING_WEEKS_AHEAD):
        d = start_date + timedelta(days=7 * wk)
        sid = _find_session_on(d.isoformat(), time_str)
        if sid:
            ok = admin_reserve(client_id, sid, 1)
            if ok:
                created += 1
    return created


def create_multi_recurring_bookings(client_id: int, slots: list[dict]):
    """
    Create bookings for multiple weekday+time slots.
    slots: [{weekday, time, slot_type, partner?}, ...]
    """
    total = 0
    for s in slots:
        total += create_recurring_bookings(
            client_id, s["weekday"], s["time"], s["slot_type"]
        )
    return total
