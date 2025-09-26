"""
admin_nudge.py
──────────────
Handles admin notifications (nudges) to Nadine for:
 - New prospects
 - Booking updates
 - Attendance issues (sick, no-show, cancel, late)
 - Deactivation requests/confirmations
"""

import logging
from datetime import datetime
from .utils import safe_execute, send_whatsapp_text
from .db import get_session
from sqlalchemy import text
import os

log = logging.getLogger(__name__)

# Nadine's WhatsApp number from env
NADINE_WA = os.getenv("NADINE_WA", "")


def _log_notification(label: str, msg: str):
    """Insert admin notification into notifications_log for audit trail."""
    with get_session() as s:
        s.execute(
            text(
                "INSERT INTO notifications_log (label, message, created_at) "
                "VALUES (:l, :m, :ts)"
            ),
            {"l": label, "m": msg, "ts": datetime.now()},
        )
    log.info(f"[ADMIN NUDGE] {label}: {msg}")


# ── Prospect Alert ──
def prospect_alert(name: str, wa_number: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"📢 Admin Alert\nHi: 📥 New Prospect: {name} ({wa_number}) at {ts}, for your urgent attention😉"
    safe_execute(send_whatsapp_text, NADINE_WA, msg, label="prospect_alert")
    _log_notification("prospect_alert", msg)


# ── Booking Update ──
def booking_update(name: str, session_type: str, day: str, time: str, dob: str | None = None, health: str | None = None):
    msg = (
        f"✅ Booking Added\n"
        f"{name} ({session_type.title()})\n"
        f"Recurring: {day} at {time}"
    )
    if dob:
        msg += f"\nDOB: {dob}"
    if health:
        msg += f"\nHealth: {health}"

    safe_execute(send_whatsapp_text, NADINE_WA, msg, label="booking_update")
    _log_notification("booking_update", msg)


# ── Attendance Status (old generic, kept for compatibility) ──
def status_update(name: str, status: str):
    msg = f"⚠️ {name} marked as {status.upper()} today."
    safe_execute(send_whatsapp_text, NADINE_WA, msg, label="status_update")
    _log_notification("status_update", msg)


# ── Attendance Update (new, detailed) ──
def attendance_update(wa_number: str, status: str, session_date, session_type: str | None):
    """Notify Nadine about client attendance changes (sick, cancelled, late)."""

    # Look up client name if possible
    name = wa_number
    with get_session() as s:
        row = s.execute(
            text("SELECT name FROM clients WHERE wa_number=:wa"),
            {"wa": wa_number},
        ).first()
        if row and row[0]:
            name = row[0]

    when = session_date.strftime("%a %d %b") if session_date else "today"
    stype = session_type.capitalize() if session_type else "Session"

    if status == "sick":
        msg = f"🤒 Attendance Alert\n{name} marked as SICK for {when} ({stype})."
    elif status == "cancelled":
        msg = f"❌ Attendance Alert\n{name} CANCELLED {when} ({stype})."
    elif status == "late":
        msg = f"⌛ Attendance Alert\n{name} is RUNNING LATE for {when} ({stype})."
    else:
        msg = f"⚠ Attendance Alert\n{name} updated status={status} for {when} ({stype})."

    safe_execute(send_whatsapp_text, NADINE_WA, msg, label=f"attendance_{status}")
    _log_notification(f"attendance_{status}", msg)


# ── Deactivation ──
def request_deactivate(name: str, wa: str):
    msg = f"❔ Deactivation requested for {name}. Confirm?"
    safe_execute(send_whatsapp_text, NADINE_WA, msg, label="request_deactivate")
    _log_notification("request_deactivate", msg)


def confirm_deactivate(name: str, wa: str):
    msg = f"✅ Client {name} has been deactivated."
    safe_execute(send_whatsapp_text, NADINE_WA, msg, label="confirm_deactivate")
    _log_notification("confirm_deactivate", msg)
