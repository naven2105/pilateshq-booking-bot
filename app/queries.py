# app/queries.py
"""
Queries Module
--------------
Business-facing query functions used by router.py.
Delegates data access to crud.py and reads some static values from config.py.
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Optional

from . import crud
from . import config

# ──────────────────────────────────────────────────────────────────────────────
# Booking Management (Clients)
# ──────────────────────────────────────────────────────────────────────────────

def get_next_lesson(client_id: int) -> Optional[Dict]:
    """Return the next confirmed lesson for a client."""
    return crud.get_next_lesson(client_id)


def get_sessions_this_week(client_id: int) -> List[Dict]:
    """Return all confirmed sessions for a client in the current week."""
    return crud.get_sessions_this_week(client_id)


def cancel_next_lesson(client_id: int) -> bool:
    """Cancel the client’s next confirmed lesson. Return True if updated."""
    return crud.cancel_next_lesson(client_id)


def get_weekly_schedule() -> List[Dict]:
    """Return all sessions for the coming week."""
    return crud.get_weekly_schedule()

# ──────────────────────────────────────────────────────────────────────────────
# Attendance & Participation
# ──────────────────────────────────────────────────────────────────────────────

def get_session_attendees(session_id: int) -> List[str]:
    """Return the list of client names attending a specific session."""
    return crud.get_session_attendees(session_id)


def get_lessons_left_this_month(client_id: int) -> int:
    """Return the number of confirmed lessons for a client in the current month."""
    return crud.get_lessons_left_this_month(client_id)


def get_clients_for_time(date_str: str, time_str: str) -> List[str]:
    """Return names of clients booked for a given date and time."""
    return crud.get_clients_for_time(date_str, time_str)


def get_clients_today() -> int:
    """Return the count of clients booked for today."""
    return crud.get_clients_today()


def get_cancellations_today() -> List[Dict]:
    """Return all cancellations for today with client and session info."""
    return crud.get_cancellations_today()


def get_clients_without_bookings_this_week() -> List[str]:
    """Return names of clients who have no confirmed bookings this week."""
    return crud.get_clients_without_bookings_this_week()


def get_weekly_recap() -> List[Dict]:
    """Return all sessions from the past 7 days with attendance counts."""
    return crud.get_weekly_recap()

# ──────────────────────────────────────────────────────────────────────────────
# Client Lookup (Admin)
# ──────────────────────────────────────────────────────────────────────────────

def get_client_sessions(client_name: str) -> List[Dict]:
    """Return confirmed sessions for a given client by name."""
    return crud.get_client_sessions(client_name)


def get_hours_until_next_lesson(client_id: int) -> float:
    """Return hours until the client’s next confirmed session today."""
    return crud.get_hours_until_next_lesson(client_id)

# ──────────────────────────────────────────────────────────────────────────────
# Pricing & Services
# ──────────────────────────────────────────────────────────────────────────────

def get_service_price(service_name: str) -> float:
    """Return price for a given service (e.g., 'Reformer Duo')."""
    try:
        return float(crud.get_service_price(service_name) or 0.0)
    except Exception:
        return 0.0

# ──────────────────────────────────────────────────────────────────────────────
# General Information (no DB)
# ──────────────────────────────────────────────────────────────────────────────

def get_today_date() -> str:
    """Return today’s date as string (yyyy-mm-dd)."""
    return datetime.today().strftime("%Y-%m-%d")


def get_current_time() -> str:
    """Return the current system time as string (HH:MM)."""
    return datetime.now().strftime("%H:%M")


def get_studio_address() -> str:
    """Return the studio’s address from config (fallback to known address)."""
    addr = getattr(config, "STUDIO_ADDRESS", "").strip()
    return addr or "106 Wilmington Crescent, Lyndhurst"


def get_studio_rules() -> str:
    """Return the studio’s rules from config or a sensible default."""
    rules = getattr(config, "STUDIO_RULES", "").strip()
    return rules or "Please arrive 5 min early, wear socks, and cancel at least 12 hours in advance."
