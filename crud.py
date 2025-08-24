# crud.py
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from db import get_session


# ---------- Clients ----------

def get_or_create_client(wa_number: str, name: str = "") -> Dict[str, Any]:
    """
    Ensure a client exists; return dict row.
    """
    with get_session() as s:
        # Try fetch
        row = s.execute(
            text("""
                SELECT id, wa_number, name, plan, household_id, birthday_day, birthday_month, medical_notes, notes
                FROM clients
                WHERE wa_number = :wa
                LIMIT 1
            """),
            {"wa": wa_number},
        ).mappings().first()
        if row:
            return dict(row)

        # Create
        s.execute(
            text("""
                INSERT INTO clients (wa_number, name)
                VALUES (:wa, :nm)
            """),
            {"wa": wa_number, "nm": name or ""},
        )
        # Re-fetch
        row = s.execute(
            text("""
                SELECT id, wa_number, name, plan, household_id, birthday_day, birthday_month, medical_notes, notes
                FROM clients
                WHERE wa_number = :wa
                LIMIT 1
            """),
            {"wa": wa_number},
        ).mappings().first()
        return dict(row)


# ---------- Sessions / Availability ----------

def list_available_slots(
    days: int = 14,
    min_seats: int = 1,
    limit: int = 10,
    start_from: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    Return upcoming open sessions with at least `min_seats` free.
    """
    start_from = start_from or date.today()
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                  id,
                  session_date,
                  start_time,
                  capacity,
                  booked_count,
                  (capacity - booked_count) AS seats_left,
                  status
                FROM sessions
                WHERE session_date >= :start_date
                  AND session_date <  :end_date
                  AND status = 'open'
                  AND (capacity - booked_count) >= :min_seats
                ORDER BY session_date, start_time
                LIMIT :limit
            """),
            {
                "start_date": start_from,
                "end_date": start_from + timedelta(days=days),
                "min_seats": min_seats,
                "limit": limit,
            },
        ).mappings().all()
        return [dict(r) for r in rows]


def list_good_group_slots(
    days: int = 14,
    min_group_left: int = 3,
    limit: int = 10,
    start_from: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    Convenience: show slots with >= `min_group_left` seats remaining (useful to fill groups).
    """
    return list_available_slots(
        days=days,
        min_seats=min_group_left,
        limit=limit,
        start_from=start_from,
    )


def hold_or_reserve_slot(session_id: int, seats: int = 1) -> Optional[Dict[str, Any]]:
    """
    Atomically increment booked_count if capacity allows.
    Returns updated session row dict, or None if no capacity.
    """
    with get_session() as s:
        row = s.execute(
            text("""
                UPDATE sessions
                SET
                  booked_count = booked_count + :seats,
                  status = CASE
                             WHEN (booked_count + :seats) >= capacity THEN 'full'
                             ELSE status
                           END
                WHERE id = :sid
                  AND (booked_count + :seats) <= capacity
                RETURNING id, session_date, start_time, capacity, booked_count, status
            """),
            {"sid": session_id, "seats": seats},
        ).mappings().first()
        return dict(row) if row else None


def release_slot(session_id: int, seats: int = 1) -> Optional[Dict[str, Any]]:
    """
    Decrement booked_count (not below 0) and reopen status.
    Returns updated session row dict, or None if session not found.
    """
    with get_session() as s:
        row = s.execute(
            text("""
                UPDATE sessions
                SET
                  booked_count = GREATEST(0, booked_count - :seats),
                  status = 'open'
                WHERE id = :sid
                RETURNING id, session_date, start_time, capacity, booked_count, status
            """),
            {"sid": session_id, "seats": seats},
        ).mappings().first()
        return dict(row) if row else None


def daily_schedule(the_day: date) -> List[Dict[str, Any]]:
    """
    Return all sessions for a given date (any status), ordered by time.
    """
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT id, session_date, start_time, capacity, booked_count, (capacity - booked_count) AS seats_left, status, notes
                FROM sessions
                WHERE session_date = :d
                ORDER BY start_time
            """),
            {"d": the_day},
        ).mappings().all()
        return [dict(r) for r in rows]
