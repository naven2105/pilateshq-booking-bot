from sqlalchemy import text
from typing import Optional, Dict, List
from .db import get_session
from .config import TZ_NAME

def create_cancel_request(booking_id: int, client_id: int, session_id: int, reason: str = "", via: str = "client") -> Dict:
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO cancel_requests (booking_id, client_id, session_id, reason, via, status)
                VALUES (:bid, :cid, :sid, :reason, :via, 'open')
                RETURNING id, booking_id, client_id, session_id, status, created_at
            """),
            {"bid": booking_id, "cid": client_id, "sid": session_id, "reason": reason[:400], "via": via},
        ).mappings().first()
        return dict(row)

def get_cancel_request(req_id: int) -> Optional[Dict]:
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT cr.*, c.name, c.wa_number, s.session_date, s.start_time,
                       b.status AS booking_status
                FROM cancel_requests cr
                JOIN clients  c ON c.id = cr.client_id
                JOIN sessions s ON s.id = cr.session_id
                JOIN bookings b ON b.id = cr.booking_id
                WHERE cr.id = :rid
            """),
            {"rid": req_id},
        ).mappings().first()
        return dict(row) if row else None

def list_open_cancel_requests(limit: int = 20) -> List[Dict]:
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT cr.id, cr.booking_id, cr.client_id, cr.session_id, cr.reason, cr.created_at,
                       c.name, c.wa_number, s.session_date, s.start_time
                FROM cancel_requests cr
                JOIN clients  c ON c.id = cr.client_id
                JOIN sessions s ON s.id = cr.session_id
                WHERE cr.status = 'open'
                ORDER BY cr.created_at
                LIMIT :lim
            """),
            {"lim": int(limit)},
        ).mappings().all()
        return [dict(r) for r in rows]

def mark_cancel_request(req_id: int, new_status: str) -> None:
    with get_session() as s:
        s.execute(
            text("""
                UPDATE cancel_requests
                SET status = :st, processed_at = CASE WHEN :st IN ('processed','declined') THEN now() ELSE processed_at END
                WHERE id = :rid
            """),
            {"rid": req_id, "st": new_status},
        )

def apply_booking_cancellation(booking_id: int) -> bool:
    """
    Sets booking -> 'cancelled' and decrements the session.booked_count (but not below 0).
    Returns True if a booking row was updated, else False (already cancelled / missing).
    """
    with get_session() as s:
        # Move booking to cancelled if it is still confirmed
        res = s.execute(
            text("""
                UPDATE bookings
                SET status = 'cancelled'
                WHERE id = :bid AND status = 'confirmed'
                RETURNING session_id
            """),
            {"bid": booking_id},
        ).mappings().first()
        if not res:
            return False
        sess_id = res["session_id"]
        # Decrement session booked_count safely
        s.execute(
            text("""
                UPDATE sessions
                SET booked_count = GREATEST(booked_count - 1, 0)
                WHERE id = :sid
            """),
            {"sid": sess_id},
        )
        return True


def create_cancel_request(booking_id: int, client_id: int, session_id: int, reason: str = "", via: str = "client") -> Dict:
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO cancel_requests (booking_id, client_id, session_id, reason, via, status)
                VALUES (:bid, :cid, :sid, :reason, :via, 'open')
                RETURNING id, booking_id, client_id, session_id, status, created_at
            """),
            {"bid": booking_id, "cid": client_id, "sid": session_id, "reason": reason[:400], "via": via},
        ).mappings().first()
        return dict(row)

def get_cancel_request(req_id: int) -> Optional[Dict]:
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT cr.*, c.name, c.wa_number, s.session_date, s.start_time,
                       b.status AS booking_status
                FROM cancel_requests cr
                JOIN clients  c ON c.id = cr.client_id
                JOIN sessions s ON s.id = cr.session_id
                JOIN bookings b ON b.id = cr.booking_id
                WHERE cr.id = :rid
            """),
            {"rid": req_id},
        ).mappings().first()
        return dict(row) if row else None

def list_open_cancel_requests(limit: int = 20) -> List[Dict]:
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT cr.id, cr.booking_id, cr.client_id, cr.session_id, cr.reason, cr.created_at,
                       c.name, c.wa_number, s.session_date, s.start_time
                FROM cancel_requests cr
                JOIN clients  c ON c.id = cr.client_id
                JOIN sessions s ON s.id = cr.session_id
                WHERE cr.status = 'open'
                ORDER BY cr.created_at
                LIMIT :lim
            """),
            {"lim": int(limit)},
        ).mappings().all()
        return [dict(r) for r in rows]

def mark_cancel_request(req_id: int, new_status: str) -> None:
    with get_session() as s:
        s.execute(
            text("""
                UPDATE cancel_requests
                SET status = :st, processed_at = CASE WHEN :st IN ('processed','declined') THEN now() ELSE processed_at END
                WHERE id = :rid
            """),
            {"rid": req_id, "st": new_status},
        )

def apply_booking_cancellation(booking_id: int) -> bool:
    """
    Sets booking -> 'cancelled' and decrements the session.booked_count (but not below 0).
    Returns True if a booking row was updated, else False (already cancelled / missing).
    """
    with get_session() as s:
        # Move booking to cancelled if it is still confirmed
        res = s.execute(
            text("""
                UPDATE bookings
                SET status = 'cancelled'
                WHERE id = :bid AND status = 'confirmed'
                RETURNING session_id
            """),
            {"bid": booking_id},
        ).mappings().first()
        if not res:
            return False
        sess_id = res["session_id"]
        # Decrement session booked_count safely
        s.execute(
            text("""
                UPDATE sessions
                SET booked_count = GREATEST(booked_count - 1, 0)
                WHERE id = :sid
            """),
            {"sid": sess_id},
        )
        return True
