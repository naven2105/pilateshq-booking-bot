# crud.py
"""
CRUD Module
-----------
Handles all database interactions for the PilatesHQ chatbot.
Uses SQLAlchemy ORM session for queries and updates.
"""

from typing import List, Dict, Optional
from datetime import date, datetime, timedelta
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from .db import db_session
from .models import Client, Booking, Session, Pricing


# 🟢 Booking Management (Clients)

def get_next_lesson(client_id: int) -> Optional[Dict]:
    """Fetch next confirmed lesson for a client."""
    session = (
        db_session.query(Session)
        .join(Booking, Booking.session_id == Session.id)
        .filter(
            Booking.client_id == client_id,
            Booking.status == "confirmed",
            Session.session_date >= date.today(),
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
    """Fetch all confirmed sessions for a client in the current week."""
    today = date.today()
    end_of_week = today + timedelta(days=7)

    sessions = (
        db_session.query(Session)
        .join(Booking, Booking.session_id == Session.id)
        .filter(
            Booking.client_id == client_id,
            Booking.status == "confirmed",
            Session.session_date.between(today, end_of_week),
        )
        .order_by(Session.session_date, Session.start_time)
        .all()
    )

    return [
        {
            "date": s.session_date.strftime("%Y-%m-%d"),
            "time": s.start_time.strftime("%H:%M"),
            "status": s.status,
        }
        for s in sessions
    ]


def cancel_next_lesson(client_id: int) -> bool:
    """Cancel the client’s next confirmed lesson."""
    booking = (
        db_session.query(Booking)
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Booking.client_id == client_id,
            Booking.status == "confirmed",
            Session.session_date >= date.today(),
        )
        .order_by(Session.session_date, Session.start_time)
        .first()
    )
    if booking:
        booking.status = "cancelled"
        db_session.commit()
        return True
    return False


def get_weekly_schedule() -> List[Dict]:
    """Fetch all sessions for the coming week."""
    today = date.today()
    end_of_week = today + timedelta(days=7)

    sessions = (
        db_session.query(Session)
        .filter(Session.session_date.between(today, end_of_week))
        .order_by(Session.session_date, Session.start_time)
        .all()
    )

    return [
        {
            "date": s.session_date.strftime("%Y-%m-%d"),
            "time": s.start_time.strftime("%H:%M"),
            "capacity": s.capacity,
            "status": s.status,
        }
        for s in sessions
    ]


# 🔵 Attendance & Participation

def get_session_attendees(session_id: int) -> List[str]:
    """Fetch names of clients in a session."""
    clients = (
        db_session.query(Client.name)
        .join(Booking, Booking.client_id == Client.id)
        .filter(Booking.session_id == session_id, Booking.status == "confirmed")
        .all()
    )
    return [c[0] for c in clients]


def get_lessons_left_this_month(client_id: int) -> int:
    """Count lessons left for client in current month."""
    today = date.today()
    start_of_month = today.replace(day=1)
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)

    count = (
        db_session.query(func.count(Booking.id))
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Booking.client_id == client_id,
            Booking.status == "confirmed",
            Session.session_date >= start_of_month,
            Session.session_date < next_month,
        )
        .scalar()
    )
    return count or 0


def get_clients_for_time(date_str: str, time_str: str) -> List[str]:
    """Fetch clients booked for given date and time."""
    clients = (
        db_session.query(Client.name)
        .join(Booking, Booking.client_id == Client.id)
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Session.session_date == date_str,
            Session.start_time == time_str,
            Booking.status == "confirmed",
        )
        .all()
    )
    return [c[0] for c in clients]


def get_clients_today() -> int:
    """Count clients booked for today."""
    count = (
        db_session.query(func.count(Booking.id))
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Session.session_date == date.today(),
            Booking.status == "confirmed",
        )
        .scalar()
    )
    return count or 0


def get_cancellations_today() -> List[Dict]:
    """Fetch cancellations for today."""
    cancellations = (
        db_session.query(Client.name, Session.session_date, Session.start_time)
        .join(Booking, Booking.client_id == Client.id)
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Session.session_date == date.today(),
            Booking.status == "cancelled",
        )
        .all()
    )
    return [
        {"client": c[0], "date": c[1].strftime("%Y-%m-%d"), "time": c[2].strftime("%H:%M")}
        for c in cancellations
    ]


def get_clients_without_bookings_this_week() -> List[str]:
    """Fetch clients with no bookings this week."""
    today = date.today()
    end_of_week = today + timedelta(days=7)

    booked_ids = (
        db_session.query(Booking.client_id)
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Session.session_date.between(today, end_of_week),
            Booking.status == "confirmed",
        )
        .distinct()
        .all()
    )
    booked_ids = [b[0] for b in booked_ids]

    clients = db_session.query(Client.name).filter(~Client.id.in_(booked_ids)).all()
    return [c[0] for c in clients]


def get_weekly_recap() -> List[Dict]:
    """Fetch all sessions from past 7 days with attendance counts."""
    today = date.today()
    last_week = today - timedelta(days=7)

    sessions = (
        db_session.query(Session.session_date, Session.start_time, func.count(Booking.id))
        .outerjoin(Booking, Booking.session_id == Session.id)
        .filter(Session.session_date.between(last_week, today))
        .group_by(Session.session_date, Session.start_time)
        .order_by(Session.session_date, Session.start_time)
        .all()
    )

    return [
        {"date": s[0].strftime("%Y-%m-%d"), "time": s[1].strftime("%H:%M"), "count": s[2]}
        for s in sessions
    ]


# 🟠 Client Lookup (Admin)

def get_client_sessions(client_name: str) -> List[Dict]:
    """Fetch sessions for a given client by name."""
    sessions = (
        db_session.query(Session.session_date, Session.start_time)
        .join(Booking, Booking.session_id == Session.id)
        .join(Client, Booking.client_id == Client.id)
        .filter(Client.name.ilike(f"%{client_name}%"), Booking.status == "confirmed")
        .order_by(Session.session_date, Session.start_time)
        .all()
    )
    return [
        {"date": s[0].strftime("%Y-%m-%d"), "time": s[1].strftime("%H:%M")}
        for s in sessions
    ]


def get_hours_until_next_lesson(client_id: int) -> float:
    """Calculate hours until client’s next lesson today."""
    session = (
        db_session.query(Session)
        .join(Booking, Booking.session_id == Session.id)
        .filter(
            Booking.client_id == client_id,
            Booking.status == "confirmed",
            Session.session_date == date.today(),
        )
        .order_by(Session.start_time)
        .first()
    )
    if not session:
        return 0.0
    delta = datetime.combine(session.session_date, session.start_time) - datetime.now()
    return round(delta.total_seconds() / 3600, 1)


# 🟣 Pricing & Services

def get_service_price(service_name: str) -> float:
    """Fetch price for a service (e.g., Reformer Duo)."""
    price = (
        db_session.query(Pricing.price)
        .filter(Pricing.service_name.ilike(service_name))
        .scalar()
    )
    return price or 0.0
