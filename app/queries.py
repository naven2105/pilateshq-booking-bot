# app/queries.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date, time
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session as OrmSession

from .db import db_session
from .models import Client, Session, Booking

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Client-facing queries
# ──────────────────────────────────────────────────────────────────────────────

def get_next_lesson(client_id: int) -> Optional[Tuple[date, time]]:
    """Return the next confirmed booking for the client (date, time), or None."""
    now = datetime.now()
    today = now.date()
    with db_session() as s:  # type: OrmSession
        row = (
            s.query(Session.session_date, Session.start_time)
            .join(Booking, Booking.session_id == Session.id)
            .filter(
                Booking.client_id == client_id,
                Booking.status == "confirmed",
                # either later today, or any future date
                ((Session.session_date == today) & (Session.start_time >= now.time()))
                | (Session.session_date > today),
            )
            .order_by(Session.session_date.asc(), Session.start_time.asc())
            .first()
        )
        return row if row else None


def get_sessions_this_week(client_id: int, window_days: int = 7) -> List[Tuple[date, time]]:
    """Return a list of (date, time) for confirmed bookings in the next N days."""
    start = datetime.now().date()
    end = start + timedelta(days=max(1, window_days) - 1)
    with db_session() as s:
        rows = (
            s.query(Session.session_date, Session.start_time)
            .join(Booking, Booking.session_id == Session.id)
            .filter(
                Booking.client_id == client_id,
                Booking.status == "confirmed",
                Session.session_date >= start,
                Session.session_date <= end,
            )
            .order_by(Session.session_date.asc(), Session.start_time.asc())
            .all()
        )
        return rows


def cancel_next_lesson(client_id: int) -> bool:
    """
    Cancel the client's next confirmed session and decrement the session.booked_count
    (bounded at 0). Returns True if a booking was cancelled.
    """
    now = datetime.now()
    today = now.date()
    with db_session() as s:
        # Find the next confirmed booking (FOR UPDATE to avoid race on the same row)
        nxt = (
            s.query(Booking.id, Booking.session_id, Session.session_date, Session.start_time)
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Booking.client_id == client_id,
                Booking.status == "confirmed",
                ((Session.session_date == today) & (Session.start_time >= now.time()))
                | (Session.session_date > today),
            )
            .order_by(Session.session_date.asc(), Session.start_time.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if not nxt:
            return False

        booking_id, session_id, _, _ = nxt

        # Mark booking cancelled
        s.query(Booking).filter(Booking.id == booking_id).update({"status": "cancelled"})

        # Decrement session.booked_count safely
        sess = s.query(Session).filter(Session.id == session_id).with_for_update().one()
        new_count = max(0, (sess.booked_count or 0) - 1)
        sess.booked_count = new_count

        s.commit()
        log.info("[cancel-next] client_id=%s session_id=%s booked_count->%s", client_id, session_id, new_count)
        return True


def get_weekly_schedule() -> List[Tuple[date, time, str]]:
    """
    Generic weekly schedule preview (all confirmed bookings, next 7 days).
    Returns list of (date, time, client_name).
    """
    start = datetime.now().date()
    end = start + timedelta(days=6)
    with db_session() as s:
        rows = (
            s.query(Session.session_date, Session.start_time, Client.name)
            .join(Booking, Booking.session_id == Session.id)
            .join(Client, Client.id == Booking.client_id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date >= start,
                Session.session_date <= end,
            )
            .order_by(Session.session_date.asc(), Session.start_time.asc())
            .all()
        )
        return rows

# ──────────────────────────────────────────────────────────────────────────────
# Admin-facing queries
# ──────────────────────────────────────────────────────────────────────────────

def get_client_sessions(client_name: str) -> List[Tuple[date, time]]:
    """Admin: list all upcoming confirmed sessions for a client name (fuzzy case-insensitive)."""
    today = datetime.now().date()
    qname = (client_name or "").strip()
    if not qname:
        return []
    with db_session() as s:
        rows = (
            s.query(Session.session_date, Session.start_time)
            .join(Booking, Booking.session_id == Session.id)
            .join(Client, Client.id == Booking.client_id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date >= today,
                func.lower(Client.name).like(f"%{qname.lower()}%"),
            )
            .order_by(Session.session_date.asc(), Session.start_time.asc())
            .all()
        )
        return rows


def get_clients_for_time(date_str: str, hhmm: str) -> List[str]:
    """Admin: list client names booked for a given date (YYYY-MM-DD) and time (HH:MM)."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        d = datetime.now().date()
    try:
        t = datetime.strptime(hhmm, "%H:%M").time()
    except Exception:
        t = time(9, 0)
    with db_session() as s:
        rows = (
            s.query(Client.name)
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date == d,
                Session.start_time == t,
            )
            .order_by(Client.name.asc())
            .all()
        )
        return [r[0] for r in rows]


def get_clients_today() -> List[Tuple[time, str]]:
    """Admin: list (time, client_name) for today's confirmed sessions."""
    today = datetime.now().date()
    with db_session() as s:
        rows = (
            s.query(Session.start_time, Client.name)
            .join(Booking, Booking.session_id == Session.id)
            .join(Client, Client.id == Booking.client_id)
            .filter(Booking.status == "confirmed", Session.session_date == today)
            .order_by(Session.start_time.asc(), Client.name.asc())
            .all()
        )
        return rows


def get_cancellations_today() -> List[Tuple[time, str]]:
    """Admin: list (time, client_name) for today's cancellations."""
    today = datetime.now().date()
    with db_session() as s:
        rows = (
            s.query(Session.start_time, Client.name)
            .join(Booking, Booking.session_id == Session.id)
            .join(Client, Client.id == Booking.client_id)
            .filter(Booking.status == "cancelled", Session.session_date == today)
            .order_by(Session.start_time.asc(), Client.name.asc())
            .all()
        )
        return rows

# ──────────────────────────────────────────────────────────────────────────────
# Simple info helpers (anyone)
# ──────────────────────────────────────────────────────────────────────────────

def get_today_date() -> str:
    return datetime.now().strftime("%A, %d %B %Y")

def get_current_time() -> str:
    return datetime.now().strftime("%H:%M")

def get_studio_address() -> str:
    return "PilatesHQ Studio, 123 Main Rd, Cape Town"

def get_studio_rules() -> str:
    return "Please arrive 5 minutes early; bring a towel; cancellations within 12 hours may be charged."
