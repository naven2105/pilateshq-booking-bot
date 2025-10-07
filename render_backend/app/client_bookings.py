"""
client_bookings.py
──────────────────
Handles client booking queries (view, cancel next, cancel specific).
"""

import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, safe_execute

log = logging.getLogger(__name__)


def show_bookings(wa_number: str):
    """Show upcoming sessions for a client in a clean format."""
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT s.session_date, s.start_time, s.session_type
                FROM bookings b
                JOIN sessions s ON b.session_id = s.id
                JOIN clients c ON b.client_id = c.id
                WHERE c.wa_number = :wa
                  AND b.status = 'confirmed'
                  AND s.session_date >= CURRENT_DATE
                ORDER BY s.session_date, s.start_time
                LIMIT 5
            """),
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
    for session_date, start_time, session_type in rows:
        day = session_date.strftime("%a %d %b")
        time = start_time.strftime("%H:%M")
        stype = session_type.capitalize() if session_type else "Session"
        lines.append(f"• {day} {time} — {stype} Reformer")

    msg = "\n".join(lines)
    safe_execute(send_whatsapp_text, wa_number, msg, label="client_bookings_ok")


def cancel_next(wa_number: str):
    """Cancel the next upcoming booking for the client."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT b.id, s.session_date, s.start_time
                FROM bookings b
                JOIN sessions s ON b.session_id = s.id
                JOIN clients c ON b.client_id = c.id
                WHERE c.wa_number = :wa
                  AND b.status = 'confirmed'
                  AND s.session_date >= CURRENT_DATE
                ORDER BY s.session_date, s.start_time
                LIMIT 1
            """),
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

        bid, session_date, start_time = row
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:id"), {"id": bid})
        dt = f"{session_date.strftime('%a %d %b')} {start_time.strftime('%H:%M')}"

    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"❌ Your next session on {dt} has been cancelled.",
        label="client_cancel_next",
    )


def cancel_specific(wa_number: str, day: str, time: str):
    """Cancel a specific session by day + time (e.g. 'Tue' and '09:00')."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT b.id, s.session_date, s.start_time
                FROM bookings b
                JOIN sessions s ON b.session_id = s.id
                JOIN clients c ON b.client_id = c.id
                WHERE c.wa_number = :wa
                  AND b.status = 'confirmed'
                  AND s.session_date >= CURRENT_DATE
                  AND to_char(s.session_date, 'Dy') ILIKE :day
                  AND to_char(s.start_time, 'HH24:MI') = :time
                LIMIT 1
            """),
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

        bid, session_date, start_time = row
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:id"), {"id": bid})
        dt = f"{session_date.strftime('%a %d %b')} {start_time.strftime('%H:%M')}"

    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"❌ Your session on {dt} has been cancelled.",
        label="client_cancel_specific_ok",
    )
