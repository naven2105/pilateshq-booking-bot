#app/crud.py
"""
CRUD Module
──────────────────────────────
Centralised DB access for PilatesHQ chatbot.
Handles clients, bookings, sessions, and pricing data.
"""

import logging
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from .db import db_session
from .models import Client, Booking, Session, Pricing

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Utility Helpers
# ──────────────────────────────────────────────

def _today() -> date:
    return datetime.now().date()

def _date_range(days: int = 7):
    start = _today()
    end = start + timedelta(days=days)
    return start, end


# ──────────────────────────────────────────────
# Client-Facing Queries
# ──────────────────────────────────────────────

def get_next_lesson(client_id: int) -> Optional[Dict]:
    """Return the next confirmed session for the client."""
    with db_session() as s:
        session = (
            s.query(Session)
            .join(Booking, Booking.session_id == Session.id)
            .filter(
                Booking.client_id == client_id,
                Booking.status == "confirmed",
                Session.session_date >= _today(),
            )
            .order_by(Session.session_date, Session.start_time)
            .first()
        )
        if not session:
            return None
        return {
            "date": session.session_date.strftime("%Y-%m-%d"),
            "time": session.start_time.strftime("%H:%M"),
            "status": session.status,
        }


def get_sessions_this_week(client_id: int) -> List[Dict]:
    """Return all confirmed sessions for the next 7 days."""
    start, end = _date_range(7)
    with db_session() as s:
        sessions = (
            s.query(Session)
            .join(Booking, Booking.session_id == Session.id)
            .filter(
                Booking.client_id == client_id,
                Booking.status == "confirmed",
                Session.session_date.between(start, end),
            )
            .order_by(Session.session_date, Session.start_time)
            .all()
        )
        return [
            {
                "date": ses.session_date.strftime("%Y-%m-%d"),
                "time": ses.start_time.strftime("%H:%M"),
                "status": ses.status,
            }
            for ses in sessions
        ]


def cancel_next_lesson(client_id: int) -> bool:
    """Cancel the client's next confirmed lesson."""
    with db_session() as s:
        booking = (
            s.query(Booking)
            .join(Session, Booking.session_id == Session.id)
            .filter(
                Booking.client_id == client_id,
                Booking.status == "confirmed",
                Session.session_date >= _today(),
            )
            .order_by(Session.session_date, Session.start_time)
            .first()
        )
        if booking:
            booking.status = "cancelled"
            s.commit()
            log.info(f"[cancel] client_id={client_id} session_id={booking.session_id}")
            return True
        return False


# ──────────────────────────────────────────────
# Admin / Reporting Queries
# ──────────────────────────────────────────────

def get_weekly_schedule() -> List[Dict]:
    """Return upcoming sessions for the next 7 days."""
    start, end = _date_range(7)
    with db_session() as s:
        sessions = (
            s.query(Session)
            .filter(Session.session_date.between(start, end))
            .order_by(Session.session_date, Session.start_time)
            .all()
        )
        return [
            {
                "date": ses.session_date.strftime("%Y-%m-%d"),
                "time": ses.start_time.strftime("%H:%M"),
                "capacity": ses.capacity,
                "status": ses.status,
            }
            for ses in sessions
        ]


def get_client_sessions_for_month(client_id: int, year: int, month: int) -> List[Dict]:
    """Return all confirmed sessions for a client in a given month (for invoices)."""
    start = date(year, month, 1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    with db_session() as s:
        sessions = (
            s.query(Session.session_date, Session.start_time, Session.session_type)
            .join(Booking, Booking.session_id == Session.id)
            .filter(
                Booking.client_id == client_id,
                Booking.status == "confirmed",
                Session.session_date >= start,
                Session.session_date < next_month,
            )
            .order_by(Session.session_date, Session.start_time)
            .all()
        )
        return [
            {
                "date": d.strftime("%Y-%m-%d"),
                "time": t.strftime("%H:%M"),
                "type": st,
            }
            for d, t, st in sessions
        ]


def get_session_price(session_type: str) -> float:
    """Return price per session type (single, duo, group)."""
    with db_session() as s:
        p = (
            s.query(Pricing.price)
            .filter(Pricing.service_name.ilike(session_type))
            .scalar()
        )
        return float(p or 0.0)


def get_cancellations_today() -> List[Dict]:
    """Return today's cancellations."""
    today = _today()
    with db_session() as s:
        cancellations = (
            s.query(Client.name, Session.session_date, Session.start_time)
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Booking.session_id == Session.id)
            .filter(Session.session_date == today, Booking.status == "cancelled")
            .all()
        )
        return [
            {
                "client": n,
                "date": d.strftime("%Y-%m-%d"),
                "time": t.strftime("%H:%M"),
            }
            for n, d, t in cancellations
        ]


# ──────────────────────────────────────────────
# Analytics / Insights
# ──────────────────────────────────────────────

def get_clients_without_bookings_this_week() -> List[str]:
    """List clients who have no confirmed sessions in the next 7 days."""
    start, end = _date_range(7)
    with db_session() as s:
        booked_ids = (
            s.query(Booking.client_id)
            .join(Session, Booking.session_id == Session.id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date.between(start, end),
            )
            .distinct()
            .all()
        )
        booked_ids = [b[0] for b in booked_ids]
        unbooked = s.query(Client.name).filter(~Client.id.in_(booked_ids)).all()
        return [u[0] for u in unbooked]


def get_weekly_recap() -> List[Dict]:
    """Return attendance recap for past 7 days."""
    today = _today()
    last_week = today - timedelta(days=7)
    with db_session() as s:
        rows = (
            s.query(Session.session_date, Session.start_time, func.count(Booking.id))
            .outerjoin(Booking, Booking.session_id == Session.id)
            .filter(Session.session_date.between(last_week, today))
            .group_by(Session.session_date, Session.start_time)
            .order_by(Session.session_date, Session.start_time)
            .all()
        )
        return [
            {"date": d.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"), "count": c}
            for d, t, c in rows
        ]
