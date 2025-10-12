# app/client_attendance.py
"""
client_attendance.py
────────────────────
Handles attendance updates from clients:
 - Sick today
 - Cannot attend / cancel today
 - Running late

Now integrated with Google Sheets via Apps Script Webhook.
"""

import logging
import os
import requests
from datetime import datetime
from .utils import send_whatsapp_text, safe_execute
from . import admin_nudge

log = logging.getLogger(__name__)

# Your deployed Google Apps Script Web App URL
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _post_to_apps_script(action: str, wa_number: str, status: str):
    """
    Notify Apps Script to update today's booking for a given client.
    The Apps Script locates the row in 'Sessions' by wa_number and date.
    """
    if not APPS_SCRIPT_URL:
        log.warning("⚠️ APPS_SCRIPT_URL not set; skipping Sheets update.")
        return

    try:
        payload = {
            "action": action,
            "wa_number": wa_number,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=10)
        log.info(f"📤 Sent attendance update to Apps Script: {payload} → {res.status_code}")
    except Exception as e:
        log.error(f"❌ Failed to post attendance update: {e}")


# ─────────────────────────────────────────────────────────────
# Sick Today
# ─────────────────────────────────────────────────────────────
def mark_sick_today(wa_number: str):
    """Mark today's session as 'sick' and notify admin."""
    log.info(f"[client_attendance] mark_sick_today → {wa_number}")

    # Update Google Sheet
    _post_to_apps_script("update_status_today", wa_number, "sick")

    # Notify client
    safe_execute(
        send_whatsapp_text,
        wa_number,
        "🤒 Got it — your session today is marked as *sick*. Rest well 💜",
        label="client_sick_ok",
    )

    # Notify Nadine
    admin_nudge.attendance_update(wa_number, "sick", datetime.now().date(), "session")


# ─────────────────────────────────────────────────────────────
# Cancel Today
# ─────────────────────────────────────────────────────────────
def cancel_today(wa_number: str):
    """Cancel today's session (status='cancelled')."""
    log.info(f"[client_attendance] cancel_today → {wa_number}")

    _post_to_apps_script("update_status_today", wa_number, "cancelled")

    safe_execute(
        send_whatsapp_text,
        wa_number,
        "❌ Your session today has been *cancelled*. Thanks for letting us know.",
        label="client_cancel_today_ok",
    )

    admin_nudge.attendance_update(wa_number, "cancelled", datetime.now().date(), "session")


# ─────────────────────────────────────────────────────────────
# Running Late
# ─────────────────────────────────────────────────────────────
def running_late(wa_number: str):
    """Notify Nadine that a client is running late."""
    log.info(f"[client_attendance] running_late → {wa_number}")

    safe_execute(
        send_whatsapp_text,
        wa_number,
        "⌛ Thanks for letting us know. Drive safe — Nadine has been notified.",
        label="client_late_ok",
    )

    admin_nudge.attendance_update(wa_number, "late", datetime.now().date(), "session")
