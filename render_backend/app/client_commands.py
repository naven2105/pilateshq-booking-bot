#render_backend_app/client_commands.py
"""
client_commands.py
──────────────────
Handles client booking queries (view, cancel, message Nadine).
"""

import logging
from datetime import datetime
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, safe_execute, normalize_wa
from . import admin_notify

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
                WHERE c.wa_number=:wa AND b.status='confirmed' AND s.session_date >= CURRENT_DATE
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
    for row in rows:
        dt, stime, stype = row
        day = dt.strftime("%a %d %b")
        time = stime.strftime("%H:%M")
        lines.append(f"• {day} {time} — {stype.capitalize()} Reformer")

    msg = "\n".join(lines)
    safe_execute(send_whatsapp_text, wa_number, msg, label="client_bookings_ok")


def cancel_next(wa_number: str):
    """Cancel the next upcoming booking for the client."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT b.id, s.session_date, s.start_time, c.name
                FROM bookings b
                JOIN sessions s ON b.session_id = s.id
                JOIN clients c ON b.client_id = c.id
                WHERE c.wa_number=:wa AND b.status='confirmed' AND s.session_date >= CURRENT_DATE
                ORDER BY s.session_date ASC, s.start_time ASC
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

        bid, sdate, stime, cname = row
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:id"), {"id": bid})

    dt_str = f"{sdate.strftime('%a %d %b')} at {stime.strftime('%H:%M')}"
    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"❌ Your next session on {dt_str} has been cancelled.",
        label="client_cancel_next",
    )

    # Notify Nadine
    admin_notify.notify_admin(f"❌ {cname} cancelled their next session on {dt_str}.", wa_number)


def cancel_specific(wa_number: str, day: str, time: str):
    """Cancel a specific session by day + time (loose matching)."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT b.id, s.session_date, s.start_time, c.name
                FROM bookings b
                JOIN sessions s ON b.session_id = s.id
                JOIN clients c ON b.client_id = c.id
                WHERE c.wa_number=:wa AND b.status='confirmed'
                AND to_char(s.session_date, 'Dy') ILIKE :day
                AND to_char(s.start_time, 'HH24:MI')=:time
                AND s.session_date >= CURRENT_DATE
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

        bid, sdate, stime, cname = row
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:id"), {"id": bid})

    dt_str = f"{sdate.strftime('%a %d %b')} at {stime.strftime('%H:%M')}"
    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"❌ Your session on {dt_str} has been cancelled.",
        label="client_cancel_specific_ok",
    )

    # Notify Nadine
    admin_notify.notify_admin(f"❌ {cname} cancelled specific session on {dt_str}.", wa_number)


def message_nadine(wa_number: str, cname: str, msg: str):
    """Send a free-text message from a client to Nadine."""
    if not msg:
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "⚠ Please include a message after 'message Nadine'.",
            label="client_message_fail",
        )
        return

    # Ack client
    safe_execute(
        send_whatsapp_text,
        wa_number,
        "💜 Your message has been sent to Nadine. She’ll get back to you soon.",
        label="client_message_ack",
    )

    # Forward to Nadine
    admin_notify.notify_admin(f"📩 Message from {cname} ({wa_number}):\n\n{msg}", wa_number)
