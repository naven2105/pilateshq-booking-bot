"""
client_bookings.py
──────────────────
Handles client booking queries (view, cancel next, cancel specific).
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, safe_execute

log = logging.getLogger(__name__)


def show_bookings(wa_number: str):
    """Show upcoming sessions for a client in a clean format."""
    with get_session() as s:
        rows = s.execute(
            text(
                "SELECT session_date, session_type "
                "FROM bookings "
                "WHERE wa_number=:wa AND session_date >= CURRENT_DATE "
                "ORDER BY session_date ASC "
                "LIMIT 5"
            ),
            {"wa": wa_number},
        ).fetchall()

    if not rows:
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "📅 You have no upcoming sessions booked.\n"
            "💜 Would you like to book your next class?",
            label="client_bookings_none",
        )
        return

    lines = ["📅 Your upcoming sessions:"]
    for row in rows:
        dt = row[0]
        stype = row[1].capitalize() if row[1] else "Session"
        day = dt.strftime("%a %d %b")
        time = dt.strftime("%H:%M")
        lines.append(f"• {day} {time} — {stype} Reformer")

    msg = "\n".join(lines)
    safe_execute(send_whatsapp_text, wa_number, msg, label="client_bookings_ok")


def cancel_next(wa_number: str):
    """Cancel the next upcoming booking for the client."""
    with get_session() as s:
        row = s.execute(
            text(
                "SELECT id, session_date FROM bookings "
                "WHERE wa_number=:wa AND session_date >= CURRENT_DATE "
                "ORDER BY session_date ASC LIMIT 1"
            ),
            {"wa": wa_number},
        ).first()

        if not row:
            safe_execute(
                send_whatsapp_text,
                wa_number,
                "⚠ You have no upcoming bookings to cancel.",
                label="client_cancel_none",
            )
            return

        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:id"), {"id": row[0]})
        dt = row[1].strftime("%a %d %b %H:%M")

    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"❌ Your next session on {dt} has been cancelled.",
        label="client_cancel_next",
    )


def cancel_specific(wa_number: str, day: str, time: str):
    """Cancel a specific session by day + time."""
    with get_session() as s:
        row = s.execute(
            text(
                "SELECT id, session_date FROM bookings "
                "WHERE wa_number=:wa "
                "AND to_char(session_date, 'Dy') ILIKE :day "
                "AND to_char(session_date, 'HH24:MI')=:time "
                "AND session_date >= CURRENT_DATE "
                "LIMIT 1"
            ),
            {"wa": wa_number, "day": day + "%", "time": time},
        ).first()

        if not row:
            safe_execute(
                send_whatsapp_text,
                wa_number,
                f"⚠ Could not find a booking for {day} at {time}.",
                label="client_cancel_specific_fail",
            )
            return

        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:id"), {"id": row[0]})
        dt = row[1].strftime("%a %d %b %H:%M")

    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"❌ Your session on {dt} has been cancelled.",
        label="client_cancel_specific_ok",
    )
