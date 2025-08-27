# app/crud.py
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import text

from .db import get_session


# ---------- Clients ----------

def list_clients(limit: int = 20) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id,
                   wa_number,
                   COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan
            FROM clients
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT :lim
        """), {"lim": limit}).mappings().all()
        return [dict(r) for r in rows]

def get_or_create_client(wa_number: str, name: str = "") -> Dict[str, Any]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, wa_number, name, plan, household_id,
                   birthday_day, birthday_month, medical_notes, notes
            FROM clients
            WHERE wa_number = :wa
            LIMIT 1
        """), {"wa": wa_number}).mappings().first()
        if row:
            return dict(row)
        s.execute(text("""
            INSERT INTO clients (wa_number, name)
            VALUES (:wa, :nm)
        """), {"wa": wa_number, "nm": name or ""})
        row = s.execute(text("""
            SELECT id, wa_number, name, plan, household_id,
                   birthday_day, birthday_month, medical_notes, notes
            FROM clients
            WHERE wa_number = :wa
            LIMIT 1
        """), {"wa": wa_number}).mappings().first()
        return dict(row)

def get_client_profile(client_id: int) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, wa_number,
                   COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan, birthday_day, birthday_month,
                   medical_notes, notes, household_id, created_at
            FROM clients
            WHERE id = :cid
        """), {"cid": client_id}).mappings().first()
        return dict(row) if row else None

def get_client_by_wa(wa_number: str) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, wa_number,
                   COALESCE(NULLIF(name,''),'(no name)') AS name,
                   plan, birthday_day, birthday_month,
                   medical_notes, notes, household_id, created_at
            FROM clients
            WHERE wa_number = :wa
            LIMIT 1
        """), {"wa": wa_number}).mappings().first()
        return dict(row) if row else None

def find_clients_by_name(q: str, limit: int = 3) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, name, wa_number, plan
            FROM clients
            WHERE LOWER(name) LIKE LOWER(:q)
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT :lim
        """), {"q": f"%{q}%", "lim": limit}).mappings().all()
        return [dict(r) for r in rows]


# ---------- Sessions (availability, holds) ----------

def list_available_slots(days: int = 14, min_seats: int = 1,
                         limit: int = 10, start_from: Optional[date] = None) -> List[Dict[str, Any]]:
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

def list_days_with_open_slots(days: int = 21,
                              start_from: Optional[date] = None,
                              limit_days: int = 10) -> List[Dict[str, Any]]:
    start_from = start_from or date.today()
    with get_session() as s:
        rows = s.execute(text("""
          SELECT session_date, COUNT(*) AS slots
          FROM sessions
          WHERE session_date >= :sd AND session_date < :ed
            AND status='open' AND (capacity - booked_count) > 0
          GROUP BY session_date
          ORDER BY session_date
          LIMIT :lim
        """), {"sd": start_from, "ed": start_from + timedelta(days=days), "lim": limit_days}).mappings().all()
        return [dict(r) for r in rows]

def list_slots_for_day(day: date, limit: int = 10) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
          SELECT id, start_time, (capacity - booked_count) AS seats_left
          FROM sessions
          WHERE session_date = :d AND status='open' AND (capacity - booked_count) > 0
          ORDER BY start_time
          LIMIT :lim
        """), {"d": day, "lim": limit}).mappings().all()
        return [dict(r) for r in rows]

def find_session_by_date_time(d: date, hhmm: str) -> Optional[Dict[str, Any]]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions
            WHERE session_date = :d AND start_time = :t AND status IN ('open','full')
            LIMIT 1
        """), {"d": d, "t": hhmm}).mappings().first()
        return dict(row) if row else None

def find_next_n_weekday_time(weekday: int, hhmm: str,
                             start_from: date, weeks: int = 4) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions
            WHERE session_date >= :start
              AND EXTRACT(DOW FROM session_date) = :wd
              AND start_time = :t
            ORDER BY session_date
            LIMIT :lim
        """), {"start": start_from, "wd": weekday, "t": hhmm, "lim": weeks}).mappings().all()
        return [dict(r) for r in rows]

def hold_or_reserve_slot(session_id: int, seats: int = 1) -> Optional[Dict[str, Any]]:
    if not session_id or seats <= 0:
        return None
    with get_session() as s:
        slot = s.execute(text("""
            SELECT id, capacity, booked_count
            FROM sessions
            WHERE id = :sid FOR UPDATE
        """), {"sid": session_id}).mappings().first()
        if not slot:
            return None
        if slot["booked_count"] + seats > slot["capacity"]:
            return None
        row = s.execute(text("""
            UPDATE sessions
            SET booked_count = booked_count + :seats,
                status = CASE WHEN booked_count + :seats >= capacity THEN 'full' ELSE 'open' END
            WHERE id = :sid
            RETURNING id, session_date, start_time, capacity, booked_count, status
        """), {"sid": session_id, "seats": seats}).mappings().first()
        return dict(row) if row else None

def release_slot(session_id: int, seats: int = 1) -> Optional[Dict[str, Any]]:
    if not session_id or seats <= 0:
        return None
    with get_session() as s:
        row = s.execute(text("""
            UPDATE sessions
            SET booked_count = GREATEST(0, booked_count - :seats), status='open'
            WHERE id = :sid
            RETURNING id, session_date, start_time, capacity, booked_count, status
        """), {"sid": session_id, "seats": seats}).mappings().first()
        return dict(row) if row else None


# ---------- Bookings (client ↔ session link) ----------

def add_session_client(session_id: int, client_id: int,
                       seats: int = 1, status: str = "confirmed") -> Optional[Dict[str, Any]]:
    """Legacy helper used by earlier flow; creates/updates 'bookings' row only (no session count mutation)."""
    if not session_id or not client_id or seats <= 0:
        return None
    with get_session() as s:
        row = s.execute(text("""
          INSERT INTO bookings (session_id, client_id, seats, status)
          VALUES (:sid, :cid, :seats, :status)
          ON CONFLICT (client_id, session_id)
          DO UPDATE SET seats=EXCLUDED.seats, status=EXCLUDED.status
          RETURNING id
        """), {"sid": session_id, "cid": client_id, "seats": seats, "status": status}).mappings().first()
        return dict(row) if row else None

def create_booking(session_id: int, client_id: int,
                   seats: int = 1, status: str = "confirmed") -> Optional[Dict[str, Any]]:
    """Atomic booking: lock session, insert/UPSERT booking, increment session booked_count."""
    if not session_id or not client_id or seats <= 0:
        return None
    with get_session() as s:
        slot = s.execute(text("""
            SELECT id, capacity, booked_count
            FROM sessions
            WHERE id=:sid FOR UPDATE
        """), {"sid": session_id}).mappings().first()
        if not slot or (slot["booked_count"] + seats) > slot["capacity"]:
            return None
        row = s.execute(text("""
            INSERT INTO bookings (session_id, client_id, seats, status)
            VALUES (:sid, :cid, :seats, :status)
            ON CONFLICT (client_id, session_id)
            DO UPDATE SET seats=EXCLUDED.seats, status=EXCLUDED.status
            RETURNING id
        """), {"sid": session_id, "cid": client_id, "seats": seats, "status": status}).mappings().first()
        s.execute(text("""
            UPDATE sessions
               SET booked_count = booked_count + :seats,
                   status = CASE WHEN booked_count + :seats >= capacity THEN 'full' ELSE status END
             WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        return dict(row) if row else None

def cancel_booking(session_id: int, client_id: int) -> bool:
    with get_session() as s:
        b = s.execute(text("""
            SELECT id, seats
            FROM bookings
            WHERE session_id=:sid AND client_id=:cid
        """), {"sid": session_id, "cid": client_id}).mappings().first()
        if not b:
            return False
        seats = b["seats"]
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:bid"),
                  {"bid": b["id"]})
        s.execute(text("""
            UPDATE sessions
               SET booked_count = GREATEST(0, booked_count - :seats),
                   status='open'
             WHERE id = :sid
        """), {"sid": session_id, "seats": seats})
        return True

def list_bookings_for_session(session_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT b.id, b.client_id, b.seats, b.status,
                   c.name, c.wa_number
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            WHERE b.session_id = :sid
            ORDER BY b.id DESC
            LIMIT :lim
        """), {"sid": session_id, "lim": limit}).mappings().all()
        return [dict(r) for r in rows]

def create_recurring_from_slot(base_session_id: int, client_id: int,
                               weeks: int = 4, seats: int = 1) -> Dict[str, int]:
    """Book same weekday/time for next N weeks based on a base session."""
    if not base_session_id or not client_id or weeks <= 0 or seats <= 0:
        return {"created": 0, "skipped": 0}
    created = skipped = 0
    with get_session() as s:
        base = s.execute(text("""
            SELECT id, session_date, start_time FROM sessions WHERE id=:sid
        """), {"sid": base_session_id}).mappings().first()
        if not base:
            return {"created": 0, "skipped": 0}
        base_date = base["session_date"]
        start_time = base["start_time"]
        for k in range(weeks):
            target_date = base_date + timedelta(days=7*k)
            tgt = s.execute(text("""
                SELECT id, capacity, booked_count
                FROM sessions
                WHERE session_date=:d AND start_time=:t FOR UPDATE
            """), {"d": target_date, "t": start_time}).mappings().first()
            if not tgt or (tgt["booked_count"] + seats) > tgt["capacity"]:
                skipped += 1
                continue
            s.execute(text("""
                INSERT INTO bookings (session_id, client_id, seats, status)
                VALUES (:sid,:cid,:seats,'confirmed')
                ON CONFLICT (client_id, session_id)
                DO UPDATE SET seats=EXCLUDED.seats, status='confirmed'
            """), {"sid": tgt["id"], "cid": client_id, "seats": seats})
            s.execute(text("""
                UPDATE sessions
                   SET booked_count = booked_count + :seats,
                       status = CASE WHEN booked_count + :seats >= capacity THEN 'full' ELSE status END
                 WHERE id = :sid
            """), {"sid": tgt["id"], "seats": seats})
            created += 1
    return {"created": created, "skipped": skipped}
