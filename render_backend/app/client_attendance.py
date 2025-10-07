"""
client_attendance.py
────────────────────
Handles attendance updates from clients:
 - Sick today
 - Cannot attend / cancel today
 - Running late
"""

import logging
from datetime import date
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, safe_execute
from . import admin_nudge

log = logging.getLogger(__name__)


def _get_today_booking(wa_number: str):
    """Return today's booking row (id, session_date, session_type) or None."""
    with get_session() as s:
        row = s.execute(
            text(
                "SELECT id, session_date, session_type "
                "FROM bookings "
                "WHERE wa_number=:wa "
                "AND session_date=CURRENT_DATE "
                "AND status='booked' "
                "LIMIT 1"
            ),
            {"wa": wa_number},
        ).first()
        return row


def mark_sick_today(wa_number: str):
    """Mark today's session as sick."""
    row = _get_today_booking(wa_number)

    if not row:
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "⚠ You don’t have a booked session today.",
            label="client_sick_none",
        )
        return

    with get_session() as s:
        s.execute(text("UPDATE bookings SET status='sick' WHERE id=:id"), {"id": row[0]})

    dt = row[1].strftime("%a %d %b")
    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"🤒 Got it — your session today ({dt}) is marked as sick. Rest well 💜",
        label="client_sick_ok",
    )

    # Admin nudge
    admin_nudge.attendance_update(wa_number, "sick", row[1], row[2])


def cancel_today(wa_number: str):
    """Cancel today's session."""
    row = _get_today_booking(wa_number)

    if not row:
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "⚠ You don’t have a booked session today.",
            label="client_cancel_today_none",
        )
        return

    with get_session() as s:
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:id"), {"id": row[0]})

    dt = row[1].strftime("%a %d %b")
    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"❌ Your session today ({dt}) has been cancelled.",
        label="client_cancel_today_ok",
    )

    # Admin nudge
    admin_nudge.attendance_update(wa_number, "cancelled", row[1], row[2])


def running_late(wa_number: str):
    """Notify that the client is running late (no DB change)."""
    row = _get_today_booking(wa_number)

    # Client always gets confirmation
    safe_execute(
        send_whatsapp_text,
        wa_number,
        "⌛ Thanks for letting us know. Drive safe — Nadine has been notified.",
        label="client_late_ok",
    )

    # Admin nudge even if no booking today
    if row:
        admin_nudge.attendance_update(wa_number, "late", row[1], row[2])
    else:
        admin_nudge.attendance_update(wa_number, "late", None, None)
