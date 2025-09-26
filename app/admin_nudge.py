"""
admin_nudge.py
──────────────
Handles admin notifications (nudges) to Nadine for:
 - New prospects
 - Booking updates
 - Attendance issues (sick, no-show, cancel)
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


# ── Attendance Status ──
def status_update(name: str, status: str):
    msg = f"⚠️ {name} marked as {status.upper()} today."
    safe_execute(send_whatsapp_text, NADINE_WA, msg, label="status_update")
    _log_notification("status_update", msg)


# ── Deactivation ──
def request_deactivate(name: str, wa: str):
    msg = f"❔ Deactivation requested for {name}. Confirm?"
    safe_execute(send_whatsapp_text, NADINE_WA, msg, label="request_deactivate")
    _log_notification("request_deactivate", msg)


def confirm_deactivate(name: str, wa: str):
    msg = f"✅ Client {name} has been deactivated."
    safe_execute(send_whatsapp_text, NADINE_WA, msg, label="confirm_deactivate")
    _log_notification("confirm_deactivate", msg)
